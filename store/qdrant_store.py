"""Qdrant Cloud vector store — production backend for RegWatch.

Drop-in replacement for ``RegWatchVectorStore`` (ChromaDB): identical public methods
(``ingest_version`` / ``query_active`` / ``get_chunks_for_version``) so call sites switch
via the ``store.get_vector_store`` factory with no code change.

Design notes (see docs/BUILD_PLAN.md):
- **Global** collections (``regwatch_active`` / ``regwatch_history``), not per-tenant —
  regulatory text is identical across tenants and there is no per-tenant upload. The tenant
  lens lives in Postgres (impacts/tasks), not in the vectors.
- Collection vector size is pinned to the active embedder's ``dim``. On a provider switch
  (Gemini↔Jina) the dims differ, so init refuses a mismatched existing collection and tells
  you to re-index — embeddings from different providers are not comparable.
"""

from __future__ import annotations

import uuid

from config.settings import get_secret
from ingestion.processor import ProcessedChunk
from store.embeddings import get_embedder

ACTIVE_COLLECTION = "regwatch_active"
HISTORY_COLLECTION = "regwatch_history"


class QdrantVectorStore:
    def __init__(self, url: str | None = None, api_key: str | None = None):
        from qdrant_client import QdrantClient

        url = url or get_secret("QDRANT_URL")
        api_key = api_key or get_secret("QDRANT_API_KEY")
        if not url:
            raise RuntimeError("QDRANT_URL is required for the Qdrant backend.")
        self.client = QdrantClient(url=url, api_key=api_key)
        self.embedder = get_embedder()
        self._ensure_collections()

    # ── collections ──────────────────────────────────────────────────────────

    def _ensure_collections(self) -> None:
        from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

        # Keyword payload indexes are REQUIRED before filtering/deleting by these fields
        # (active.delete by doc_id, query source filter, history scroll by version).
        indexed_fields = {
            ACTIVE_COLLECTION: ("doc_id", "source"),
            HISTORY_COLLECTION: ("version", "doc_id"),
        }
        existing = {c.name for c in self.client.get_collections().collections}
        for name in (ACTIVE_COLLECTION, HISTORY_COLLECTION):
            if name not in existing:
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=self.embedder.dim, distance=Distance.COSINE),
                )
            else:
                got = self.client.get_collection(name).config.params.vectors.size
                if got != self.embedder.dim:
                    raise RuntimeError(
                        f"Collection '{name}' has vector dim {got} but the active embedder "
                        f"'{self.embedder.name}' produces dim {self.embedder.dim}. Provider vectors are not "
                        f"comparable — re-index the corpus after switching EMBEDDING_PROVIDER."
                    )
            for field in indexed_fields[name]:
                try:
                    self.client.create_payload_index(
                        collection_name=name,
                        field_name=field,
                        field_schema=PayloadSchemaType.KEYWORD,
                    )
                except Exception:
                    pass  # index already exists — idempotent

    @staticmethod
    def _point_id(chunk_id: str) -> str:
        # Qdrant ids must be int or UUID; derive a deterministic UUID from the chunk_id.
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id))

    def _build_points(self, chunks: list[ProcessedChunk], source: str, embeddings: list[list[float]]):
        from qdrant_client.models import PointStruct

        return [
            PointStruct(
                id=self._point_id(c.chunk_id),
                vector=emb,
                payload={
                    "chunk_id": c.chunk_id,
                    "doc_id": c.doc_id,
                    "version": c.version,
                    "section_title": c.section_title or "",
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                    "source": source,
                    "text": c.text,
                },
            )
            for c, emb in zip(chunks, embeddings)
        ]

    # ── ingestion ────────────────────────────────────────────────────────────

    def ingest_version(self, chunks: list[ProcessedChunk], source: str, is_latest: bool = True) -> None:
        if not chunks:
            return
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        embeddings = self.embedder.embed_documents([c.text for c in chunks])
        points = self._build_points(chunks, source, embeddings)

        # History keeps every version forever.
        self.client.upsert(collection_name=HISTORY_COLLECTION, points=points)

        if is_latest:
            doc_id = chunks[0].doc_id
            self.client.delete(
                collection_name=ACTIVE_COLLECTION,
                points_selector=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
            )
            self.client.upsert(collection_name=ACTIVE_COLLECTION, points=points)

    # ── retrieval ────────────────────────────────────────────────────────────

    def query_active(self, query: str, n_results: int = 5, source_filter: str | None = None) -> list[dict]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        query_vector = self.embedder.embed_queries([query])[0]
        flt = (
            Filter(must=[FieldCondition(key="source", match=MatchValue(value=source_filter))])
            if source_filter
            else None
        )
        result = self.client.query_points(
            collection_name=ACTIVE_COLLECTION,
            query=query_vector,
            limit=n_results,
            query_filter=flt,
            with_payload=True,
        )
        out: list[dict] = []
        for point in result.points:
            payload = point.payload or {}
            out.append(
                {
                    "chunk_id": payload.get("chunk_id"),
                    "text": payload.get("text", ""),
                    "metadata": {
                        "doc_id": payload.get("doc_id"),
                        "version": payload.get("version"),
                        "section_title": payload.get("section_title", ""),
                        "source": payload.get("source"),
                    },
                    "distance": 1.0 - point.score,
                    "relevance": point.score,
                }
            )
        return out

    def get_chunks_for_version(self, version_id: str) -> list[ProcessedChunk]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        points, _ = self.client.scroll(
            collection_name=HISTORY_COLLECTION,
            scroll_filter=Filter(must=[FieldCondition(key="version", match=MatchValue(value=version_id))]),
            with_payload=True,
            limit=2000,
        )
        chunks: list[ProcessedChunk] = []
        for point in points:
            p = point.payload or {}
            chunks.append(
                ProcessedChunk(
                    chunk_id=p.get("chunk_id"),
                    doc_id=p["doc_id"],
                    version=p["version"],
                    text=p.get("text", ""),
                    section_title=p.get("section_title"),
                    page_number=0,
                    char_start=p.get("char_start", 0),
                    char_end=p.get("char_end", 0),
                )
            )
        return chunks
