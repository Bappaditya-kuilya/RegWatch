"""Pipeline — trigger a run for the tenant and list past runs.

A simple in-process per-tenant cooldown rate-limits /run (sufficient for the single-worker
Render deployment; swap for slowapi/Redis when scaling out)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_tenant
from api.services.pipeline_service import run_pipeline_for_tenant
from db import repository as repo

router = APIRouter()

_RUN_COOLDOWN_SECONDS = 30
_last_run: dict[str, float] = {}


@router.post("/run")
def trigger_run(tenant: dict = Depends(get_current_tenant)):
    tid = tenant["tenant_id"]
    now = time.monotonic()
    if now - _last_run.get(tid, 0.0) < _RUN_COOLDOWN_SECONDS:
        raise HTTPException(status_code=429, detail="Pipeline run was triggered recently. Try again shortly.")
    _last_run[tid] = now
    try:
        return run_pipeline_for_tenant(tid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/runs")
def list_runs(tenant: dict = Depends(get_current_tenant)):
    return repo.list_pipeline_runs(tenant["tenant_id"])
