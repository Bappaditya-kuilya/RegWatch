"""Tenant-scoped data repository over Supabase Postgres.

Isolation is enforced at TWO layers (defense in depth):
1. Every per-tenant query runs inside ``tenant_cursor(tenant_id)`` → RLS via the
   regwatch_app role makes other tenants' rows invisible at the database.
2. Queries ALSO filter ``WHERE tenant_id = %s`` in code — testable, and the primary
   guarantee if RLS is ever misconfigured.

Global regulatory data (documents/versions/chunks/changes) is non-tenant and uses
``admin_cursor()``. Proven by tests/test_tenant_isolation.py.
"""

from __future__ import annotations

import json
import uuid

from psycopg2.extras import Json

from core.models import ComplianceTask
from db.connection import admin_cursor, tenant_cursor


# ── tenants (registry; no RLS — managed with admin connection) ───────────────

def create_tenant(name: str, slug: str) -> str:
    tenant_id = str(uuid.uuid4())
    with admin_cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s)",
            (tenant_id, name, slug),
        )
    return tenant_id


def delete_tenant(tenant_id: str) -> None:
    # Cascades to all per-tenant rows via ON DELETE CASCADE.
    with admin_cursor() as cur:
        cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))


def list_tenants() -> list[dict]:
    with admin_cursor() as cur:
        cur.execute(
            "SELECT id, name, slug, subscription_tier, is_active FROM tenants ORDER BY created_at"
        )
        cols = ("id", "name", "slug", "subscription_tier", "is_active")
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ── company profile (per-tenant, RLS) ────────────────────────────────────────

def upsert_company_profile(tenant_id: str, profile: dict) -> None:
    with tenant_cursor(tenant_id) as cur:
        cur.execute(
            "INSERT INTO company_profiles (tenant_id, profile, updated_at) "
            "VALUES (%s, %s, NOW()) "
            "ON CONFLICT (tenant_id) DO UPDATE SET profile = EXCLUDED.profile, updated_at = NOW()",
            (tenant_id, Json(profile)),
        )


def get_company_profile(tenant_id: str) -> dict | None:
    with tenant_cursor(tenant_id) as cur:
        cur.execute("SELECT profile FROM company_profiles WHERE tenant_id = %s", (tenant_id,))
        row = cur.fetchone()
    if not row:
        return None
    return json.loads(row[0]) if isinstance(row[0], str) else row[0]


# ── compliance tasks (per-tenant, RLS) ───────────────────────────────────────

_TASK_COLS = (
    "task_id", "title", "description", "priority", "deadline",
    "deadline_source", "penalty_if_missed", "citation", "action_url", "status",
)


def save_tasks(tenant_id: str, tasks: list[ComplianceTask]) -> None:
    with tenant_cursor(tenant_id) as cur:
        for t in tasks:
            cur.execute(
                "INSERT INTO compliance_tasks "
                "(tenant_id, task_id, title, description, source_change_id, deadline, "
                " deadline_source, penalty_if_missed, priority, citation, action_url, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id, task_id) DO UPDATE SET "
                "  title=EXCLUDED.title, description=EXCLUDED.description, "
                "  deadline=EXCLUDED.deadline, deadline_source=EXCLUDED.deadline_source, "
                "  penalty_if_missed=EXCLUDED.penalty_if_missed, priority=EXCLUDED.priority, "
                "  citation=EXCLUDED.citation, action_url=EXCLUDED.action_url",
                (
                    tenant_id, t.task_id, t.title, t.description, t.source_change_id, t.deadline,
                    t.deadline_source, t.penalty_if_missed, t.priority, t.citation, t.action_url, t.status,
                ),
            )


def list_tasks(tenant_id: str, status: str | None = None) -> list[dict]:
    query = (
        f"SELECT {', '.join(_TASK_COLS)} FROM compliance_tasks WHERE tenant_id = %s"
    )
    params: list = [tenant_id]
    if status:
        query += " AND status = %s"
        params.append(status)
    query += " ORDER BY priority, deadline NULLS LAST"
    with tenant_cursor(tenant_id) as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    return [dict(zip(_TASK_COLS, row)) for row in rows]


def update_task_status(tenant_id: str, task_id: str, status: str) -> int:
    ts_col = {"acknowledged": "acknowledged_at", "completed": "completed_at"}.get(status)
    with tenant_cursor(tenant_id) as cur:
        if ts_col:
            cur.execute(
                f"UPDATE compliance_tasks SET status = %s, {ts_col} = NOW() "
                "WHERE tenant_id = %s AND task_id = %s",
                (status, tenant_id, task_id),
            )
        else:
            cur.execute(
                "UPDATE compliance_tasks SET status = %s WHERE tenant_id = %s AND task_id = %s",
                (status, tenant_id, task_id),
            )
        return cur.rowcount
