from __future__ import annotations

import chromadb

from config.settings import DATA_DIR
from ingestion.processor import ProcessedChunk
from store.embeddings import get_embedder


class RegWatchVectorStore:
    def __init__(self, persist_dir: str | None = None):
        persist_path = persist_dir or str(DATA_DIR / "chromadb")
        self.client = chromadb.PersistentClient(path=persist_path)
        self.embedder = get_embedder()
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
