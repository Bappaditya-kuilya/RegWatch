"""FastAPI dependencies — Supabase clients + tenant resolution from the bearer token.

``get_current_tenant`` verifies the Supabase Auth JWT (server-side via ``auth.get_user``)
and reads the tenant_id stamped into the user's ``app_metadata`` at registration. No local
JWT secret needed, and the tenant binding can't be forged by the client.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Header, HTTPException

from api.config import config


@lru_cache(maxsize=1)
def anon_client():
    from supabase import create_client

    return create_client(config.supabase_url, config.supabase_anon_key)


@lru_cache(maxsize=1)
def service_client():
    from supabase import create_client

    return create_client(config.supabase_url, config.supabase_service_key)


async def get_current_tenant(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        user = anon_client().auth.get_user(token).user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    tenant_id = (user.app_metadata or {}).get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="User is not bound to a tenant")
    return {"tenant_id": tenant_id, "email": user.email, "user_id": user.id}
