"""Run the agentic pipeline for one tenant and persist results to their rows.

Glues the (global) LangGraph pipeline to the (per-tenant) Supabase repository: loads the
tenant's profile, runs the pipeline over the global corpus, then writes the tenant's impact
assessments + compliance tasks and records the pipeline_run. Idempotent — repository upserts
collapse any LangGraph state accumulation by change_id / task_id.
"""

from __future__ import annotations

from core.models import CompanyProfile
from db import repository as repo


def run_pipeline_for_tenant(tenant_id: str, trigger: str = "manual", mode: str = "seeded") -> dict:
    profile_dict = repo.get_company_profile(tenant_id)
    if not profile_dict:
        raise ValueError("Company profile is not set for this tenant.")
    profile = CompanyProfile(**profile_dict)
    doc_ids = repo.list_document_ids()

    run_id = repo.create_pipeline_run(tenant_id, trigger=trigger, mode=mode)
    try:
        from graph.pipeline import build_pipeline

        pipeline = build_pipeline()
        result = pipeline.invoke(
            {
                "trigger": "seeded",
                "company_profile": profile,
                "user_query": "",
                "new_doc_ids": doc_ids,
                "detected_changes": [],
                "impact_assessments": [],
                "action_plan": [],
                "current_agent": "",
                "errors": [],
                "skip_diff": False,
                "human_review_needed": False,
                "run_mode": mode,
            },
            config={"configurable": {"thread_id": run_id}},
        )
        changes = result.get("detected_changes", [])
        impacts = result.get("impact_assessments", [])
        tasks = result.get("action_plan", [])

        repo.save_impacts(tenant_id, impacts)
        repo.save_tasks(tenant_id, tasks)
        repo.complete_pipeline_run(tenant_id, run_id, len(changes), len(tasks))
        return {
            "run_id": run_id,
            "status": "completed",
            "changes_detected": len(changes),
            "tasks_generated": len(tasks),
        }
    except Exception as exc:
        repo.complete_pipeline_run(tenant_id, run_id, 0, 0, status="failed", error=str(exc)[:500])
        raise
