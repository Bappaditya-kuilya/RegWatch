"""Metadata store facade — the strangler-fig seam for the document registry + version graph.

Replaces direct use of ``store.doc_registry.DocumentRegistry`` (SQLite) and
``core.version_graph.VersionGraph`` (JSON file) with one interface backed by either:

- ``local``    : the original SQLite registry + JSON graph (offline dev, no cloud needed).
- ``supabase`` : the normalized Postgres tables via ``db.repository`` (production).

Selected by ``METADATA_BACKEND`` (default 'local'). Same call sites, one env flip — so the
pipeline never hard-depends on a backend and stays demoable at every step.

Interface (all backends implement):
    hash_changed(doc_id, content_hash) -> bool
    register_version(doc_id, source, title, url, version_date, content_hash) -> (version_id, prev_id|None)
    add_chunks(doc_id, version_id, chunks) -> None
    active_version_id(doc_id) -> str | None
    previous_version_id(version_id) -> str | None
    save_change(change) -> None
    recent_changes(days=90) -> list[dict]
    list_document_ids(prefix=None) -> list[str]
    reset_corpus() -> None
"""

from __future__ import annotations

from config.settings import get_secret


class _LocalMetadataStore:
    """Adapter over the original SQLite registry + JSON version graph."""

    def __init__(self) -> None:
        from core.version_graph import VersionGraph
        from store.doc_registry import DocumentRegistry

        self._registry = DocumentRegistry()
        self._vg = VersionGraph()

    def hash_changed(self, doc_id: str, content_hash: str) -> bool:
        return self._registry.hash_changed(doc_id, content_hash)

    def register_version(self, doc_id, source, title, url, version_date, content_hash):
        previous = self._registry.get_current_version(doc_id)
        version_id = self._registry.register_new_version(
            doc_id=doc_id, source=source, title=title, url=url,
            version_date=version_date, content_hash=content_hash,
        )
        self._vg.add_document(doc_id, source, title)
        self._vg.add_version(doc_id, version_id, version_date, content_hash)
        if previous and previous != version_id:
            self._vg.supersede(version_id, previous)
        self._vg.save()
        return version_id, (previous if previous != version_id else None)

    def add_chunks(self, doc_id: str, version_id: str, chunks: list) -> None:
        for c in chunks:
            self._vg.add_chunk(version_id, c.chunk_id, c.section_title, c.char_start, c.char_end)
        self._vg.save()
        self._registry.log_ingestion(doc_id, version_id, len(chunks), False)

    def active_version_id(self, doc_id: str) -> str | None:
        return self._vg.get_active_version(doc_id)

    def previous_version_id(self, version_id: str) -> str | None:
        return self._vg.get_previous_version(version_id)

    def save_change(self, change) -> None:
        self._vg.record_change(change)
        self._vg.save()

    def recent_changes(self, days: int = 90) -> list[dict]:
        return self._vg.get_recent_changes(days=days)

    def list_document_ids(self, prefix: str | None = None) -> list[str]:
        cur = self._registry.conn.execute(
            "SELECT doc_id FROM documents WHERE doc_id LIKE ? ORDER BY doc_id",
            ((prefix + "%") if prefix else "%",),
        )
        return [row[0] for row in cur.fetchall()]

    def reset_corpus(self) -> None:
        # Local reset is handled by seed_data --clean deleting the data/ files.
        pass


class _SupabaseMetadataStore:
    """Adapter over the normalized Postgres tables (db.repository)."""

    def __init__(self) -> None:
        from db import repository

        self._repo = repository

    def hash_changed(self, doc_id, content_hash):
        return self._repo.hash_changed(doc_id, content_hash)

    def register_version(self, doc_id, source, title, url, version_date, content_hash):
        return self._repo.register_version(doc_id, source, title, url, version_date, content_hash)

    def add_chunks(self, doc_id, version_id, chunks):
        self._repo.add_chunks(doc_id, version_id, chunks)

    def active_version_id(self, doc_id):
        return self._repo.active_version_id(doc_id)

    def previous_version_id(self, version_id):
        return self._repo.previous_version_id(version_id)

    def save_change(self, change):
        self._repo.save_change(change)

    def recent_changes(self, days=90):
        return self._repo.recent_changes(days=days)

    def list_document_ids(self, prefix=None):
        return self._repo.list_document_ids(prefix=prefix)

    def reset_corpus(self):
        self._repo.reset_corpus()


def get_metadata_store():
    """Return the configured metadata store. ``METADATA_BACKEND``: 'local' (default) | 'supabase'."""
    backend = (get_secret("METADATA_BACKEND", "local") or "local").lower()
    if backend == "supabase":
        return _SupabaseMetadataStore()
    if backend == "local":
        return _LocalMetadataStore()
    raise ValueError(f"Unknown METADATA_BACKEND '{backend}'. Options: local, supabase.")
