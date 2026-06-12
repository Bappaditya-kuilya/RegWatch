"""Apply db/schema.sql to the Supabase Postgres database.

Requires DATABASE_URL (the Supabase 'Connection string -> URI', with your DB password).
DDL cannot go through the REST API / service-role key, so this uses a direct connection.

Run: PYTHONPATH=. .venv/bin/python scripts/apply_schema.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv()

EXPECTED_TABLES = [
    "tenants",
    "company_profiles",
    "tenant_sources",
    "regulatory_documents",
    "document_versions",
    "version_edges",
    "document_chunks",
    "detected_changes",
    "impact_assessments",
    "compliance_tasks",
    "pipeline_runs",
    "audit_log",
]


def _normalize(url: str) -> str:
    # Supabase poolers require TLS; add sslmode if the URI omits it.
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def main() -> int:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("ERROR: DATABASE_URL not set in .env (Supabase -> Settings -> Database -> Connection string -> URI).")
        return 2

    import psycopg2

    schema_sql = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    conn = psycopg2.connect(_normalize(url))
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(schema_sql)
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name;"
            )
            present = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()

    print("Applied db/schema.sql. Tables now present:")
    missing = []
    for t in EXPECTED_TABLES:
        ok = t in present
        print(f"  [{'x' if ok else ' '}] {t}")
        if not ok:
            missing.append(t)
    if missing:
        print(f"WARNING: missing tables: {missing}")
        return 1
    print("All expected tables present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
