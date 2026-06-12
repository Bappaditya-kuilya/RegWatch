"""Postgres connection management for the RegWatch repository.

Two cursor modes:

- ``admin_cursor()``  — connects as the configured role (Supabase 'postgres', which has
  BYPASSRLS). Use ONLY for non-tenant data: the global regulatory corpus and the tenants
  registry. Never for per-tenant rows.

- ``tenant_cursor(tenant_id)`` — drops to the owner-less ``regwatch_app`` role and sets
  ``app.tenant_id`` for the transaction, so RLS policies genuinely isolate the tenant. All
  per-tenant reads/writes go through here. ``SET LOCAL`` is transaction-scoped, so the role
  and GUC reset automatically when the transaction ends (safe with pooling).
"""

from __future__ import annotations

import contextlib

from config.settings import get_secret

_pool = None


def _dsn() -> str:
    url = get_secret("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required for the Supabase repository.")
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def get_pool():
    global _pool
    if _pool is None:
        from psycopg2.pool import ThreadedConnectionPool

        _pool = ThreadedConnectionPool(minconn=1, maxconn=8, dsn=_dsn())
    return _pool


@contextlib.contextmanager
def admin_cursor():
    """Transaction as the connecting role (BYPASSRLS). Global/non-tenant data only."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextlib.contextmanager
def tenant_cursor(tenant_id: str):
    """Transaction scoped to ``tenant_id`` with RLS enforced via the regwatch_app role."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE regwatch_app")
            cur.execute("SET LOCAL app.tenant_id = %s", (str(tenant_id),))
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)
