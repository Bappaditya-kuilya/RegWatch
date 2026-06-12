"""Vector store factory — the strangler-fig seam between ChromaDB (local/dev) and Qdrant (cloud).

Call sites use ``get_vector_store()`` instead of constructing a backend directly, so switching
the whole app to Qdrant is a one-line env change: ``VECTOR_BACKEND=qdrant``.
"""

from __future__ import annotations

from config.settings import get_secret


def get_vector_store():
    """Return the configured vector store. ``VECTOR_BACKEND`` env: 'chroma' (default) | 'qdrant'."""
    backend = (get_secret("VECTOR_BACKEND", "chroma") or "chroma").lower()
    if backend == "qdrant":
        from store.qdrant_store import QdrantVectorStore

        return QdrantVectorStore()
    if backend == "chroma":
        from store.vector_store import RegWatchVectorStore

        return RegWatchVectorStore()
    raise ValueError(f"Unknown VECTOR_BACKEND '{backend}'. Options: chroma, qdrant.")
