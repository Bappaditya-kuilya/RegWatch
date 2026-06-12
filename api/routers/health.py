"""Health endpoint — used by Render's health check and the UptimeRobot keep-alive ping.

Intentionally does NO external calls so the keep-alive ping is cheap and never flaps when
a downstream (Qdrant/Supabase/Groq) is briefly slow.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.config import SERVICE_NAME, VERSION

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": SERVICE_NAME, "version": VERSION}
