from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph

from core.llm import complete_structured, get_groq_client
from core.models import (
    ActionResponse,
    CompanyProfile,
    ComplianceTask,
    ImpactAssessment,
    ImpactResponse,
    SemanticChange,
)


class RegWatchState(TypedDict):
    trigger: str
    user_query: str
    company_profile: CompanyProfile
    new_doc_ids: list[str]
    detected_changes: Annotated[list[SemanticChange], operator.add]
    impact_assessments: Annotated[list[ImpactAssessment], operator.add]
    action_plan: list[ComplianceTask]
    current_agent: str
    errors: list[str]
    skip_diff: bool
    human_review_needed: bool
    run_mode: str


def ingest_document(doc) -> tuple[str, bool]:
    from ingestion.processor import DocumentProcessor
    from store import get_vector_store
    from store.metadata import get_metadata_store

    meta = get_metadata_store()
    vs = get_vector_store()
    processor = DocumentProcessor()

    if not meta.hash_changed(doc.doc_id, doc.content_hash):
        return "", False

    version_date = doc.published_date.date().isoformat()
    version_id, previous_version = meta.register_version(
        doc_id=doc.doc_id,
        source=doc.source,
        title=doc.title,
        url=doc.url,
        version_date=version_date,
        content_hash=doc.content_hash,
    )
    chunks = processor.process(doc, version_id)
    vs.ingest_version(chunks, source=doc.source, is_latest=True)
    meta.add_chunks(doc.doc_id, version_id, chunks)
    return doc.doc_id, previous_version is not None


def sentinel_node(state: RegWatchState) -> dict:
    if state.get("trigger") == "seeded":
        return {
            "new_doc_ids": state.get("new_doc_ids", []),
            "skip_diff": len(state.get("new_doc_ids", [])) == 0,
            "current_agent": "sentinel",
            "errors": state["errors"],
        }

    from ingestion.scrapers.fssai_scraper import FSSAIScraper
    from ingestion.scrapers.gst_scraper import GSTScraper
    from ingestion.scrapers.mca_scraper import MCAScraper

    new_doc_ids = []
    for scraper_class in (GSTScraper, MCAScraper, FSSAIScraper):
        scraper = scraper_class()
        try:
            for doc in scraper.fetch_all_new():
                doc_id, changed = ingest_document(doc)
                if doc_id and changed:
                    new_doc_ids.append(doc_id)
        except Exception as exc:
            state["errors"].append(f"{scraper_class.__name__}: {exc}")

    return {
        "new_doc_ids": new_doc_ids,
        "skip_diff": len(new_doc_ids) == 0,
        "current_agent": "sentinel",
        "errors": state["errors"],
    }


def diff_node(state: RegWatchState) -> dict:
    from core.diff_engine import SemanticDiffEngine
    from store import get_vector_store
    from store.metadata import get_metadata_store

    llm = get_groq_client()
    meta = get_metadata_store()
    vs = get_vector_store()
    engine = SemanticDiffEngine(llm)

    all_changes = []
    for doc_id in state["new_doc_ids"]:
        active_v = meta.active_version_id(doc_id)
        prev_v = meta.previous_version_id(active_v) if active_v else None
        if not prev_v or not active_v:
            continue
        old_chunks = vs.get_chunks_for_version(prev_v)
        new_chunks = vs.get_chunks_for_version(active_v)
        changes = engine.compute_diff(old_chunks, new_chunks, doc_id)
        all_changes.extend(changes)
        for change in changes:
            meta.save_change(change)

    return {"detected_changes": all_changes, "current_agent": "diff"}


def impact_mapper_node(state: RegWatchState) -> dict:
    llm = get_groq_client()
    profile = state["company_profile"]
    assessments = []

    prompt_template = """You are a compliance expert. Determine if this regulatory change
affects the described business.

BUSINESS PROFILE:
- Type: {business_type}
- Products: {products}
- HSN Codes: {hsn_codes}
- Applicable Acts: {applicable_acts}
- State: {state}

REGULATORY CHANGE:
- Type: {change_type}
- Summary: {new_summary}
- Old Rule: {old_summary}
- Source: {doc_id}

Respond ONLY with JSON:
{{
  "is_applicable": <true|false>,
  "applicability_reason": "<one sentence>",
  "affected_operations": ["<list of affected business operations>"],
  "affected_product_categories": ["<list>"],
  "risk_level": "<critical|major|minor>",
  "requires_action": <true|false>
}}"""

    for change in state["detected_changes"]:
        prompt = prompt_template.format(
            business_type=profile.business_type,
            products=", ".join(profile.product_categories),
            hsn_codes=", ".join(profile.hsn_codes),
            applicable_acts=", ".join(profile.applicable_acts),
            state=profile.state,
            change_type=change.change_type.value,
            new_summary=change.new_text_summary,
            old_summary=change.old_text_summary,
            doc_id=change.doc_id,
        )
        resp = complete_structured(llm, prompt, ImpactResponse, max_tokens=400)
        if resp is None:
            continue
        assessments.append(ImpactAssessment(change_id=change.change_id, **resp.model_dump()))

    return {"impact_assessments": assessments, "current_agent": "impact_mapper"}


def action_planner_node(state: RegWatchState) -> dict:
    llm = get_groq_client()
    applicable = [a for a in state["impact_assessments"] if a.is_applicable and a.requires_action]
    change_map = {c.change_id: c for c in state["detected_changes"]}
    tasks = []

    prompt_template = """Extract a specific compliance action from this regulatory change.

CHANGE SUMMARY: {summary}
SOURCE TEXT: {context}
AFFECTED OPERATIONS: {operations}

Respond ONLY with JSON:
{{
  "title": "<action title, max 10 words>",
  "description": "<what exactly must be done, 2-3 sentences>",
  "deadline": "<ISO date string or null>",
  "deadline_source": "<verbatim phrase from source text that states the deadline>",
  "penalty_if_missed": "<verbatim penalty clause or null>",
  "priority": <1-5, where 1 is most urgent>
}}"""

    def _parse_deadline(deadline_text: str | None, source_text: str) -> datetime | None:
        if not deadline_text or deadline_text.lower() == "null":
            return None
        try:
            parsed = datetime.fromisoformat(deadline_text)
        except ValueError:
            return None
        if parsed.year < 2026:
            return None
        if "following month" in source_text.lower():
            return None
        return parsed

    def _fallback_task(i: int, change: SemanticChange, assessment: ImpactAssessment) -> ComplianceTask:
        title = f"Review {change.change_type.value.replace('_', ' ').title()}"
        description = (
            f"Assess and implement the regulatory update for {', '.join(assessment.affected_operations) or 'affected operations'}. "
            f"Change summary: {change.new_text_summary}"
        )
        priority_map = {
            "critical": 1,
            "major": 2,
            "minor": 4,
        }
        return ComplianceTask(
            task_id=f"task_{i:04d}",
            title=title[:40],
            description=description,
            source_change_id=change.change_id,
            deadline=None,
            deadline_source="",
            penalty_if_missed=None,
            priority=priority_map.get(assessment.risk_level.value, 3),
            citation=f"{change.doc_id} - {change.affected_clauses}",
        )

    for i, assessment in enumerate(applicable):
        change = change_map.get(assessment.change_id)
        if not change:
            continue
        resp = complete_structured(
            llm,
            prompt_template.format(
                summary=change.new_text_summary,
                context=change.raw_diff_context[:1000],
                operations=", ".join(assessment.affected_operations),
            ),
            ActionResponse,
            max_tokens=400,
        )
        if resp is None:
            tasks.append(_fallback_task(i, change, assessment))
            continue
        deadline = _parse_deadline(resp.deadline, resp.deadline_source)
        tasks.append(
            ComplianceTask(
                task_id=f"task_{i:04d}",
                source_change_id=change.change_id,
                citation=f"{change.doc_id} - {change.affected_clauses}",
                deadline=deadline,
                title=resp.title,
                description=resp.description,
                deadline_source=resp.deadline_source,
                penalty_if_missed=resp.penalty_if_missed,
                priority=max(1, min(resp.priority, 5)),
            )
        )

    tasks.sort(key=lambda t: t.priority)
    return {
        "action_plan": tasks,
        "human_review_needed": any(t.priority == 1 for t in tasks),
        "current_agent": "action_planner",
    }


def should_skip_diff(state: RegWatchState) -> str:
    return "end_no_changes" if state.get("skip_diff") else "diff"


def build_pipeline():
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        memory = SqliteSaver.from_conn_string("data/checkpoints.db")
    except Exception:
        try:
            from langgraph.checkpoint.memory import InMemorySaver

            memory = InMemorySaver()
        except Exception:
            memory = None
    graph = StateGraph(RegWatchState)
    graph.add_node("sentinel", sentinel_node)
    graph.add_node("diff", diff_node)
    graph.add_node("impact_mapper", impact_mapper_node)
    graph.add_node("action_planner", action_planner_node)
    graph.set_entry_point("sentinel")
    graph.add_conditional_edges("sentinel", should_skip_diff, {"diff": "diff", "end_no_changes": END})
    graph.add_edge("diff", "impact_mapper")
    graph.add_edge("impact_mapper", "action_planner")
    graph.add_edge("action_planner", END)
    if memory is not None:
        return graph.compile(checkpointer=memory)
    return graph.compile()
