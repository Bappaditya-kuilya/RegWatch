"""Compliance tasks — list and update status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_tenant
from db import repository as repo

router = APIRouter()


@router.get("")
def list_tasks(status: str | None = None, tenant: dict = Depends(get_current_tenant)):
    return repo.list_tasks(tenant["tenant_id"], status=status)


@router.patch("/{task_id}/acknowledge")
def acknowledge(task_id: str, tenant: dict = Depends(get_current_tenant)):
    if not repo.update_task_status(tenant["tenant_id"], task_id, "acknowledged"):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "acknowledged"}


@router.patch("/{task_id}/complete")
def complete(task_id: str, tenant: dict = Depends(get_current_tenant)):
    if not repo.update_task_status(tenant["tenant_id"], task_id, "completed"):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "completed"}
