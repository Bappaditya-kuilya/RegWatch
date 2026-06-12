"""Embedding providers for RegWatch.

Free-tier, off-machine embeddings (8 GB-friendly): no local model loads, every call
is a remote HTTP request via httpx (no heavy vendor SDK).

Providers
---------
- ``gemini``  : Google ``gemini-embedding-001`` (free 1,500 req/day, #1 multilingual MTEB). Primary.
- ``jina``    : Jina ``jina-embeddings-v3`` (free 1M tokens/month, 89 langs incl. Hindi/Bengali). Fallback.

Important: Gemini and Jina live in **different embedding spaces and dimensions**. They are NOT
interchangeable per-call within one vector collection — querying a Gemini-built index with a Jina
vector returns garbage. The supported "fallback" is therefore *switch provider + re-index the corpus*
(cheap at hackathon scale), selected via the ``EMBEDDING_PROVIDER`` env var. Each provider exposes its
``name`` and ``dim`` so the vector store can record what an index was built with and refuse mismatches.
"""

from __future__ import annotations

import math
import os
import time
from typing import Protocol, runtime_checkable

import httpx

from config.settings import get_secret


class EmbeddingError(RuntimeError):
    """Non-retryable embedding failure (bad request, auth, malformed response)."""


class QuotaExceeded(EmbeddingError):
    """Provider returned 429 / quota exhausted. Caller should switch provider + re-index."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_queries(self, texts: list[str]) -> list[list[float]]: ...


# --------------------------------------------------------------------------- helpers


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


def _post_with_retry(
    client: httpx.Client,
    url: str,
    *,
    json: dict,
    headers: dict | None = None,
    max_attempts: int = 4,
) -> httpx.Response:
    """POST with bounded exponential backoff. 429 -> QuotaExceeded; other 4xx -> EmbeddingError."""
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            resp = client.post(url, json=json, headers=headers, timeout=60.0)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc
            time.sleep(min(2**attempt, 8))
            continue

        if resp.status_code == 429:
            raise QuotaExceeded(f"{url.split('?')[0]} returned 429 (quota/rate limit exhausted)")
        if 400 <= resp.status_code < 500:
            raise EmbeddingError(f"{resp.status_code} from {url.split('?')[0]}: {resp.text[:300]}")
        if resp.status_code >= 500:
            last_exc = EmbeddingError(f"{resp.status_code}: {resp.text[:200]}")
            time.sleep(min(2**attempt, 8))
            continue
        return resp

    raise EmbeddingError(f"Embedding request failed after {max_attempts} attempts: {last_exc}")


# --------------------------------------------------------------------------- Gemini


class GeminiEmbedder:
    """Google Generative Language API embeddings via REST (batchEmbedContents)."""

    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"
    BATCH_SIZE = 100  # batchEmbedContents request cap

    def __init__(self, api_key: str | None = None, model: str | None = None, dim: int | None = None):
        key = api_key or get_secret("GEMINI_API_KEY")
        if not key:
            raise EmbeddingError("GEMINI_API_KEY is required for the Gemini embedder.")
        self._key = key
        self.model = model or get_secret("GEMINI_EMBED_MODEL", "gemini-embedding-001")
        self.dim = int(dim or get_secret("GEMINI_EMBED_DIM", "1536"))
        self._client = httpx.Client()

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        url = f"{self.BASE}/{self.model}:batchEmbedContents?key={self._key}"
        out: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            payload = {
                "requests": [
                    {
                        "model": f"models/{self.model}",
                        "content": {"parts": [{"text": t}]},
                        "taskType": task_type,
                        "outputDimensionality": self.dim,
                    }
                    for t in batch
                ]
            }
            resp = _post_with_retry(self._client, url, json=payload)
            data = resp.json()
            embeddings = data.get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(batch):
                raise EmbeddingError(f"Gemini returned {len(embeddings or [])} embeddings for {len(batch)} inputs")
            # outputDimensionality < 3072 is not normalized by Google -> normalize for cosine.
            out.extend(_l2_normalize(e["values"]) for e in embeddings)
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_QUERY")


# --------------------------------------------------------------------------- Jina


class JinaEmbedder:
    """Jina AI embeddings via REST. Vectors are returned L2-normalized."""

    name = "jina"
    URL = "https://api.jina.ai/v1/embeddings"
    BATCH_SIZE = 128
    _DIMS = {"jina-embeddings-v3": 1024, "jina-embeddings-v4": 2048}

    def __init__(self, api_key: str | None = None, model: str | None = None):
        key = api_key or get_secret("JINA_API_KEY")
        if not key:
            raise EmbeddingError("JINA_API_KEY is required for the Jina embedder.")
        self._key = key
        self.model = model or get_secret("JINA_MODEL", "jina-embeddings-v3")
        self.dim = self._DIMS.get(self.model, 1024)
        self._client = httpx.Client()

    def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        out: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            payload = {"model": self.model, "task": task, "normalized": True, "input": batch}
            resp = _post_with_retry(self._client, self.URL, json=payload, headers=headers)
            rows = resp.json().get("data")
            if not isinstance(rows, list) or len(rows) != len(batch):
                raise EmbeddingError(f"Jina returned {len(rows or [])} embeddings for {len(batch)} inputs")
            rows.sort(key=lambda r: r.get("index", 0))
            out.extend(r["embedding"] for r in rows)
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "retrieval.passage")

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "retrieval.query")


# --------------------------------------------------------------------------- factory


_PROVIDERS = {"gemini": GeminiEmbedder, "jina": JinaEmbedder}


def get_embedder(provider: str | None = None) -> EmbeddingProvider:
    """Return the configured embedding provider. Defaults to ``EMBEDDING_PROVIDER`` env or 'gemini'."""
    name = (provider or get_secret("EMBEDDING_PROVIDER", "gemini") or "gemini").lower()
    if name not in _PROVIDERS:
        raise EmbeddingError(f"Unknown EMBEDDING_PROVIDER '{name}'. Options: {sorted(_PROVIDERS)}")
    return _PROVIDERS[name]()
