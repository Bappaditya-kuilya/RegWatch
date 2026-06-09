from __future__ import annotations

import os

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from ingestion.processor import ProcessedChunk

class RegWatchVectorStore:
    def __init__(self, persist_dir: str = "data/chromadb"):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.embed_fn = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        self.active = self.client.get_or_create_collection(
            name="active_chunks",
            embedding_function=self.embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
        self.history = self.client.get_or_create_collection(
            name="all_versions",
            embedding_function=self.embed_fn,
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
        self.history.add(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            metadatas=history_meta,
        )

        if is_latest:
            self.active.add(
                ids=[c.chunk_id for c in chunks],
                documents=[c.text for c in chunks],
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
        results = self.active.query(
            query_texts=[query],
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
