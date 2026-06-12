"""Proves tenant data isolation against the live Supabase database.

Skips automatically when DATABASE_URL is not configured (e.g. CI without secrets).
Creates two throwaway tenants, writes a task to each, and asserts neither the
application-layer queries nor a raw blanket query can cross the tenant boundary.
"""

from __future__ import annotations

import uuid

import pytest

from config.settings import get_secret

pytestmark = pytest.mark.skipif(
    not get_secret("DATABASE_URL"), reason="DATABASE_URL not set — Supabase isolation test skipped"
)


def _task(task_id: str, title: str):
    from core.models import ComplianceTask

    return ComplianceTask(
        task_id=task_id,
        title=title,
        description="x",
        source_change_id="chg",
        deadline=None,
        deadline_source="",
        penalty_if_missed=None,
        priority=1,
        citation="cite",
    )


def test_tenant_isolation():
    from db import repository as repo
    from db.connection import tenant_cursor

    a = repo.create_tenant("Alpha Foods", "alpha-" + uuid.uuid4().hex[:8])
    b = repo.create_tenant("Beta Foods", "beta-" + uuid.uuid4().hex[:8])
    try:
        repo.save_tasks(a, [_task("A1", "A only")])
        repo.save_tasks(b, [_task("B1", "B only")])

        # Layer 1 — application queries are tenant-scoped.
        assert {t["task_id"] for t in repo.list_tasks(a)} == {"A1"}
        assert {t["task_id"] for t in repo.list_tasks(b)} == {"B1"}

        # Layer 2 — RLS: a blanket SELECT inside tenant A's session sees only A's row,
        # even though the connecting role would otherwise see both.
        with tenant_cursor(a) as cur:
            cur.execute("SELECT count(*) FROM compliance_tasks")
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT task_id FROM compliance_tasks")
            assert cur.fetchone()[0] == "A1"

        # Cross-tenant write is rejected by RLS (WITH CHECK): A's session cannot insert a
        # row stamped for tenant B.
        with pytest.raises(Exception):
            with tenant_cursor(a) as cur:
                cur.execute(
                    "INSERT INTO compliance_tasks (tenant_id, task_id, title, priority) "
                    "VALUES (%s, 'X', 'sneaky', 1)",
                    (b,),
                )
    finally:
        repo.delete_tenant(a)
        repo.delete_tenant(b)
