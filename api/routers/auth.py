"""Auth — register a tenant + user, and login.

Registration provisions a tenant (Postgres) and a Supabase Auth user whose app_metadata
carries the tenant_id, then creates the user pre-confirmed (admin API) so login works
immediately without the email-confirmation round trip.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import anon_client, service_client
from db import repository as repo

router = APIRouter()


class RegisterIn(BaseModel):
    email: str
    password: str
    company_name: str


class LoginIn(BaseModel):
    email: str
    password: str


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "tenant"
    return f"{base}-{uuid.uuid4().hex[:6]}"


@router.post("/register")
def register(body: RegisterIn):
    tenant_id = repo.create_tenant(body.company_name, _slug(body.company_name))
    repo.upsert_company_profile(tenant_id, {})
    try:
        service_client().auth.admin.create_user(
            {
                "email": body.email,
                "password": body.password,
                "email_confirm": True,
                "app_metadata": {"tenant_id": tenant_id},
            }
        )
    except Exception as exc:
        repo.delete_tenant(tenant_id)
        raise HTTPException(status_code=400, detail=f"Registration failed: {exc}")
    return {"tenant_id": tenant_id, "email": body.email}


@router.post("/login")
def login(body: LoginIn):
    try:
        result = anon_client().auth.sign_in_with_password(
            {"email": body.email, "password": body.password}
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not result.session:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": result.session.access_token, "token_type": "bearer"}
