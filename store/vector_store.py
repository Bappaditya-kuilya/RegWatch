from __future__ import annotations

import os
from typing import Any

import chromadb
import cohere

from config.settings import DATA_DIR
from ingestion.processor import ProcessedChunk


class CohereEmbedder:
    MODEL_NAME = "embed-multilingual-v3.0"
    BATCH_SIZE = 32

    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ.get("COHERE_API_KEY")
        if not key:
            raise ValueError("COHERE_API_KEY is required for Cohere embeddings.")
        self.client = cohere.ClientV2(api_key=key)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, input_type="search_document")

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, input_type="search_query")

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for idx in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[idx : idx + self.BATCH_SIZE]
            response = self.client.embed(
                texts=batch,
                model=self.MODEL_NAME,
                input_type=input_type,
                embedding_types=["float"],
            )
            embeddings.extend(self._extract_float_embeddings(response))
        return embeddings

    def _extract_float_embeddings(self, response: Any) -> list[list[float]]:
        embeddings = getattr(response, "embeddings", None)
        if embeddings is None and isinstance(response, dict):
            embeddings = response.get("embeddings")

        if embeddings is None:
            raise ValueError("Cohere response did not contain embeddings.")

        if isinstance(embeddings, dict):
            if "float" in embeddings:
                return embeddings["float"]

        float_attr = getattr(embeddings, "float_", None)
        if float_attr is not None:
            return float_attr

        float_attr = getattr(embeddings, "float", None)
        if float_attr is not None:
            return float_attr

        if isinstance(embeddings, list):
            return embeddings

        raise ValueError("Unable to extract float embeddings from Cohere response.")


class RegWatchVectorStore:
    def __init__(self, persist_dir: str | None = None):
        persist_path = persist_dir or str(DATA_DIR / "chromadb")
        self.client = chromadb.PersistentClient(path=persist_path)
        self.embedder = CohereEmbedder()
        self.active = self.client.get_or_create_collection(
            name="regwatch_active",
            metadata={"hnsw:space": "cosine"},
        )
        self.history = self.client.get_or_create_collection(
            name="regwatch_history",
            metadata={"hnsw:space": "cosine"},
        )

    def ingest_version(self, chunks: list[ProcessedChunk], source: str, is_latest: bool = True) -> None:
        if not chunks:
            return
        if is_latest:
            existing = self.active.get(where={"doc_id": chunks[0].doc_id}, include=[])
            if existing["ids"]:
                self.active.delete(ids=existing["ids"])

        history_meta = [
            {
                "doc_id": c.doc_id,
                "version": c.version,
                "section_title": c.section_title or "",
                "char_start": c.char_start,
                "char_end": c.char_end,
                "source": source,
            }
            for c in chunks
        ]
        chunk_texts = [c.text for c in chunks]
        history_embeddings = self.embedder.embed_documents(chunk_texts)

        self.history.add(
            ids=[c.chunk_id for c in chunks],
            documents=chunk_texts,
            embeddings=history_embeddings,
            metadatas=history_meta,
        )

        if is_latest:
            self.active.add(
                ids=[c.chunk_id for c in chunks],
                documents=chunk_texts,
                embeddings=history_embeddings,
                metadatas=[
                    {
                        "doc_id": c.doc_id,
                        "version": c.version,
                        "section_title": c.section_title or "",
                        "source": source,
                    }
                    for c in chunks
                ],
            )

    def query_active(self, query: str, n_results: int = 5, source_filter: str | None = None) -> list[dict]:
        where = {"source": source_filter} if source_filter else None
        query_embedding = self.embedder.embed_queries([query])[0]
        results = self.active.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        return self._format_results(results)

    def get_chunks_for_version(self, version_id: str) -> list[ProcessedChunk]:
        results = self.history.get(where={"version": version_id}, include=["documents", "metadatas"])
        chunks: list[ProcessedChunk] = []
        ids = results.get("ids", [])
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        for i, chunk_id in enumerate(ids):
            meta = metas[i]
            chunks.append(
                ProcessedChunk(
                    chunk_id=chunk_id,
                    doc_id=meta["doc_id"],
                    version=meta["version"],
                    text=docs[i],
                    section_title=meta.get("section_title"),
                    page_number=0,
                    char_start=meta.get("char_start", 0),
                    char_end=meta.get("char_end", 0),
                )
            )
        return chunks

    def _format_results(self, raw: dict) -> list[dict]:
        out = []
        if not raw.get("ids"):
            return out
        for i, chunk_id in enumerate(raw["ids"][0]):
            out.append(
                {
                    "chunk_id": chunk_id,
                    "text": raw["documents"][0][i],
                    "metadata": raw["metadatas"][0][i],
                    "distance": raw["distances"][0][i],
                    "relevance": 1 - raw["distances"][0][i],
                }
            )
        return out
