from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id          TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    title           TEXT NOT NULL,
    current_version TEXT NOT NULL,
    first_seen      TEXT NOT NULL,
    last_updated    TEXT NOT NULL,
    url             TEXT
);

CREATE TABLE IF NOT EXISTS versions (
    version_id      TEXT PRIMARY KEY,
    doc_id          TEXT NOT NULL,
    version_date    TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    status          TEXT DEFAULT 'active',
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE TABLE IF NOT EXISTS ingestion_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id          TEXT,
    version_id      TEXT,
    ingested_at     TEXT,
    chunks_count    INTEGER,
    diff_triggered  BOOLEAN DEFAULT 0
);
"""


class DocumentRegistry:
    def __init__(self, db_path: str = "data/registry.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def is_registered(self, doc_id: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM documents WHERE doc_id = ?", (doc_id,))
        return cur.fetchone() is not None

    def hash_changed(self, doc_id: str, new_hash: str) -> bool:
        cur = self.conn.execute(
            """SELECT v.content_hash FROM versions v
               JOIN documents d ON v.version_id = d.current_version
               WHERE d.doc_id = ?""",
            (doc_id,),
        )
        row = cur.fetchone()
        if row is None:
            return True
        return row[0] != new_hash

    def get_current_version(self, doc_id: str) -> str | None:
        cur = self.conn.execute("SELECT current_version FROM documents WHERE doc_id = ?", (doc_id,))
        row = cur.fetchone()
        return row[0] if row else None

    def register_new_version(
        self,
        doc_id: str,
        source: str,
        title: str,
        url: str,
        version_date: str,
        content_hash: str,
    ) -> str:
        version_id = f"{doc_id}_v{version_date}"
        now = datetime.now().isoformat()
        self.conn.execute(
            "UPDATE versions SET status = 'superseded' WHERE doc_id = ? AND status = 'active'",
            (doc_id,),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO versions VALUES (?, ?, ?, ?, 'active')",
            (version_id, doc_id, version_date, content_hash),
        )
        self.conn.execute(
            """INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(doc_id) DO UPDATE SET
               current_version = excluded.current_version,
               last_updated = excluded.last_updated,
               title = excluded.title,
               url = excluded.url""",
            (doc_id, source, title, version_id, now, now, url),
        )
        self.conn.commit()
        return version_id

    def log_ingestion(self, doc_id: str, version_id: str, chunks_count: int, diff_triggered: bool) -> None:
        self.conn.execute(
            """INSERT INTO ingestion_log (doc_id, version_id, ingested_at, chunks_count, diff_triggered)
               VALUES (?, ?, ?, ?, ?)""",
            (doc_id, version_id, datetime.now().isoformat(), chunks_count, int(diff_triggered)),
        )
        self.conn.commit()
