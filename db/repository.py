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

from core.models import ComplianceTask, SemanticChange
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


# ── global regulatory corpus (admin; no RLS) — replaces DocumentRegistry + VersionGraph ──

def hash_changed(doc_id: str, new_hash: str) -> bool:
    """True if the doc is new or its active version's content hash differs (=> re-ingest)."""
    with admin_cursor() as cur:
        cur.execute(
            "SELECT content_hash FROM document_versions WHERE doc_id = %s AND status = 'active' LIMIT 1",
            (doc_id,),
        )
        row = cur.fetchone()
    return row is None or row[0] != new_hash


def active_version_id(doc_id: str) -> str | None:
    with admin_cursor() as cur:
        cur.execute(
            "SELECT version_id FROM document_versions WHERE doc_id = %s AND status = 'active' LIMIT 1",
            (doc_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def previous_version_id(version_id: str) -> str | None:
    with admin_cursor() as cur:
        cur.execute(
            "SELECT old_version_id FROM version_edges WHERE new_version_id = %s LIMIT 1",
            (version_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def register_version(
    doc_id: str, source: str, title: str, url: str, version_date: str, content_hash: str
) -> tuple[str, str | None]:
    """Register a new active version atomically; supersede the prior active one.

    Returns (version_id, previous_active_version_id_or_None).
    """
    version_id = f"{doc_id}_v{version_date}"
    with admin_cursor() as cur:
        cur.execute(
            "SELECT version_id FROM document_versions WHERE doc_id = %s AND status = 'active' LIMIT 1",
            (doc_id,),
        )
        row = cur.fetchone()
        previous = row[0] if row else None

        cur.execute(
            "INSERT INTO regulatory_documents "
            "(doc_id, source, title, url, current_version_id, last_updated_at) "
            "VALUES (%s,%s,%s,%s,%s,NOW()) "
            "ON CONFLICT (doc_id) DO UPDATE SET source=EXCLUDED.source, title=EXCLUDED.title, "
            "  url=EXCLUDED.url, current_version_id=EXCLUDED.current_version_id, last_updated_at=NOW()",
            (doc_id, source, title, url, version_id),
        )
        cur.execute(
            "UPDATE document_versions SET status='superseded' WHERE doc_id=%s AND status='active'",
            (doc_id,),
        )
        cur.execute(
            "INSERT INTO document_versions (version_id, doc_id, version_date, content_hash, status) "
            "VALUES (%s,%s,%s,%s,'active') ON CONFLICT (version_id) DO UPDATE SET status='active'",
            (version_id, doc_id, version_date, content_hash),
        )
        if previous and previous != version_id:
            cur.execute(
                "INSERT INTO version_edges (new_version_id, old_version_id) VALUES (%s,%s) "
                "ON CONFLICT DO NOTHING",
                (version_id, previous),
            )
    return version_id, (previous if previous != version_id else None)


def add_chunks(doc_id: str, version_id: str, chunks: list) -> None:
    with admin_cursor() as cur:
        for c in chunks:
            cur.execute(
                "INSERT INTO document_chunks (chunk_id, version_id, doc_id, section_title, char_start, char_end) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (chunk_id) DO UPDATE SET version_id=EXCLUDED.version_id, "
                "  section_title=EXCLUDED.section_title, char_start=EXCLUDED.char_start, char_end=EXCLUDED.char_end",
                (c.chunk_id, version_id, doc_id, c.section_title, c.char_start, c.char_end),
            )
        cur.execute(
            "UPDATE document_versions SET chunks_count=%s WHERE version_id=%s",
            (len(chunks), version_id),
        )


def save_change(change: SemanticChange) -> None:
    with admin_cursor() as cur:
        cur.execute(
            "INSERT INTO detected_changes "
            "(change_id, doc_id, old_version, new_version, change_type, severity, "
            " old_text_summary, new_text_summary, affected_clauses, confidence, raw_diff_context, detected_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW()) "
            "ON CONFLICT (change_id) DO UPDATE SET "
            "  old_text_summary=EXCLUDED.old_text_summary, new_text_summary=EXCLUDED.new_text_summary, "
            "  severity=EXCLUDED.severity, change_type=EXCLUDED.change_type, confidence=EXCLUDED.confidence",
            (
                change.change_id, change.doc_id, change.old_version, change.new_version,
                change.change_type.value, change.severity.value, change.old_text_summary,
                change.new_text_summary, Json(change.affected_clauses), change.confidence,
                change.raw_diff_context,
            ),
        )


def recent_changes(days: int = 90) -> list[dict]:
    cols = ("change_id", "doc_id", "change_type", "severity", "old_text_summary", "new_text_summary", "new_version", "detected_at")
    with admin_cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(cols)} FROM detected_changes "
            "WHERE detected_at >= NOW() - (%s || ' days')::interval ORDER BY detected_at DESC",
            (str(days),),
        )
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def list_document_ids(prefix: str | None = None) -> list[str]:
    with admin_cursor() as cur:
        if prefix:
            cur.execute("SELECT doc_id FROM regulatory_documents WHERE doc_id LIKE %s ORDER BY doc_id", (prefix + "%",))
        else:
            cur.execute("SELECT doc_id FROM regulatory_documents ORDER BY doc_id")
        return [row[0] for row in cur.fetchall()]


def reset_corpus() -> None:
    """Truncate the global regulatory corpus (used by `seed_data --clean`)."""
    with admin_cursor() as cur:
        cur.execute(
            "TRUNCATE regulatory_documents, document_versions, version_edges, "
            "document_chunks, detected_changes RESTART IDENTITY CASCADE"
        )


# ── impact assessments + pipeline runs (per-tenant, RLS) ─────────────────────

def save_impacts(tenant_id: str, impacts: list) -> None:
    with tenant_cursor(tenant_id) as cur:
        for a in impacts:
            cur.execute(
                "INSERT INTO impact_assessments "
                "(tenant_id, change_id, is_applicable, applicability_reason, "
                " affected_operations, affected_product_categories, risk_level, requires_action) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id, change_id) DO UPDATE SET "
                "  is_applicable=EXCLUDED.is_applicable, applicability_reason=EXCLUDED.applicability_reason, "
                "  affected_operations=EXCLUDED.affected_operations, "
                "  affected_product_categories=EXCLUDED.affected_product_categories, "
                "  risk_level=EXCLUDED.risk_level, requires_action=EXCLUDED.requires_action",
                (
                    tenant_id, a.change_id, a.is_applicable, a.applicability_reason,
                    Json(a.affected_operations), Json(a.affected_product_categories),
                    a.risk_level.value, a.requires_action,
                ),
            )


def create_pipeline_run(tenant_id: str, trigger: str = "manual", mode: str = "seeded") -> str:
    run_id = str(uuid.uuid4())
    with tenant_cursor(tenant_id) as cur:
        cur.execute(
            "INSERT INTO pipeline_runs (id, tenant_id, trigger, mode, status) "
            "VALUES (%s,%s,%s,%s,'running')",
            (run_id, tenant_id, trigger, mode),
        )
    return run_id


def complete_pipeline_run(
    tenant_id: str, run_id: str, changes: int, tasks: int,
    status: str = "completed", error: str | None = None,
) -> None:
    with tenant_cursor(tenant_id) as cur:
        cur.execute(
            "UPDATE pipeline_runs SET status=%s, changes_detected=%s, tasks_generated=%s, "
            "completed_at=NOW(), error_message=%s WHERE id=%s AND tenant_id=%s",
            (status, changes, tasks, error, run_id, tenant_id),
        )


def list_pipeline_runs(tenant_id: str, limit: int = 20) -> list[dict]:
    cols = ("id", "trigger", "mode", "status", "changes_detected", "tasks_generated", "started_at", "completed_at")
    with tenant_cursor(tenant_id) as cur:
        cur.execute(
            f"SELECT {', '.join(cols)} FROM pipeline_runs WHERE tenant_id=%s "
            "ORDER BY started_at DESC LIMIT %s",
            (tenant_id, limit),
        )
        return [dict(zip(cols, row)) for row in cur.fetchall()]
