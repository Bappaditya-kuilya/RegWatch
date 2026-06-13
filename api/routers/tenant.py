"""Tenant profile — read and update the company profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_tenant
from core.models import CompanyProfile
from db import repository as repo

router = APIRouter()


@router.get("")
def get_tenant(tenant: dict = Depends(get_current_tenant)):
    return {
        "tenant_id": tenant["tenant_id"],
        "email": tenant["email"],
        "profile": repo.get_company_profile(tenant["tenant_id"]),
    }


@router.put("/profile")
def update_profile(body: dict, tenant: dict = Depends(get_current_tenant)):
    try:
        profile = CompanyProfile(**body)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid company profile: {exc}")
    repo.upsert_company_profile(tenant["tenant_id"], profile.model_dump())
    return {"status": "saved"}
