"""Query — version-aware RAG answer with intent routing (the contextual-fidelity surface)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_current_tenant
from db import repository as repo

router = APIRouter()


class QueryIn(BaseModel):
    query: str


@router.post("")
def query(body: QueryIn, tenant: dict = Depends(get_current_tenant)):
    from agents.query_agent import QueryAgent

    profile = repo.get_company_profile(tenant["tenant_id"]) or {}
    return QueryAgent().answer(body.query, profile)
