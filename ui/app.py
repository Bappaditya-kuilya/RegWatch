from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.query_agent import QueryAgent
from core.models import CompanyProfile
from graph.pipeline import build_pipeline

st.set_page_config(page_title="RegWatch - Regulatory Intelligence", page_icon="⚖️", layout="wide")


@st.cache_resource
def load_profile() -> CompanyProfile:
    with open("config/company_profile.json", encoding="utf-8") as f:
        return CompanyProfile(**json.load(f))


@st.cache_resource
def get_pipeline():
    return build_pipeline()


@st.cache_resource
def get_query_agent():
    return QueryAgent()


def get_seeded_demo_doc_ids() -> list[str]:
    conn = sqlite3.connect("data/registry.db")
    try:
        rows = conn.execute(
            "select doc_id from documents where doc_id = 'DEMO_NAMKEEN_NOTICE'"
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def get_all_seeded_doc_ids() -> list[str]:
    conn = sqlite3.connect("data/registry.db")
    try:
        rows = conn.execute("select doc_id from documents order by doc_id").fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


profile = load_profile()

with st.sidebar:
    st.markdown("### Company")
    st.info(f"**{profile.company_name}**\n\n{profile.business_type}\n\nGSTIN: `{profile.gstin}`")
    st.markdown("---")
    run_mode = st.radio(
        "Run Mode",
        ["Demo Mode", "Seeded Dataset", "Live Scrape"],
        help="Demo Mode is the stable hackathon path. Seeded Dataset uses all ingested docs. Live Scrape fetches fresh portal data.",
    )
    st.markdown("### Data Sources")
    st.success("GST Circulars - Active")
    st.success("MCA21 Notifications - Active")
    st.success("FSSAI Orders - Active")
    st.success("eGazette - Active")
    st.markdown("---")
    st.caption("Demo mode uses the controlled versioned namkeen document for stable diff output.")
    if st.button("Run Pipeline Now", type="primary"):
        with st.spinner("Running RegWatch pipeline..."):
            pipeline = get_pipeline()
            if run_mode == "Demo Mode":
                trigger = "seeded"
                seeded_doc_ids = get_seeded_demo_doc_ids()
            elif run_mode == "Seeded Dataset":
                trigger = "seeded"
                seeded_doc_ids = get_all_seeded_doc_ids()
            else:
                trigger = "manual"
                seeded_doc_ids = []
            result = pipeline.invoke(
                {
                    "trigger": trigger,
                    "company_profile": profile,
                    "user_query": "",
                    "new_doc_ids": seeded_doc_ids,
                    "detected_changes": [],
                    "impact_assessments": [],
                    "action_plan": [],
                    "current_agent": "",
                    "errors": [],
                    "skip_diff": False,
                    "human_review_needed": False,
                    "run_mode": run_mode,
                },
                config={"configurable": {"thread_id": "streamlit-manual-run"}},
            )
            st.session_state["last_result"] = result
            st.success("Pipeline complete.")

tab_dashboard, tab_tasks, tab_query, tab_graph = st.tabs(
    ["Dashboard", "Compliance Tasks", "Ask RegWatch", "Version Graph"]
)

with tab_dashboard:
    result = st.session_state.get("last_result", {})
    changes = result.get("detected_changes", [])
    tasks = result.get("action_plan", [])
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Changes Detected", len(changes))
    col2.metric(
        "Applicable to You",
        sum(1 for a in result.get("impact_assessments", []) if getattr(a, "is_applicable", False)),
    )
    col3.metric("Compliance Tasks", len(tasks))
    col4.metric("Critical Tasks", sum(1 for t in tasks if t.priority == 1))
    if result.get("errors"):
        st.error("\n".join(result["errors"]))
    if changes:
        st.markdown("### Recent Regulatory Changes")
        for change in changes[:10]:
            sev_color = {"critical": "🔴", "major": "🟡", "minor": "🟢"}.get(change.severity.value, "⚪")
            with st.expander(f"{sev_color} [{change.change_type.value.upper()}] {change.doc_id}"):
                st.markdown(f"**What changed:** {change.new_text_summary}")
                st.markdown(f"**Previously:** {change.old_text_summary}")
                st.caption(
                    f"Confidence: {change.confidence:.0%} | Clauses: {', '.join(change.affected_clauses)}"
                )

with tab_tasks:
    tasks = st.session_state.get("last_result", {}).get("action_plan", [])
    if not tasks:
        st.info("No compliance tasks yet. Run the pipeline from the sidebar.")
    for task in tasks:
        priority_label = ["", "🔴 Critical", "🟠 High", "🟡 Medium", "🔵 Low", "⚪ Informational"][task.priority]
        with st.expander(f"{priority_label} - {task.title}"):
            st.markdown(task.description)
            if task.deadline:
                st.warning(f"**Deadline:** {task.deadline.strftime('%d %B %Y')}")
            if task.penalty_if_missed:
                st.error(f"**Penalty:** {task.penalty_if_missed}")
            st.caption(f"Source: {task.citation}")

with tab_query:
    st.markdown("### Ask about any regulation")
    query = st.text_input("e.g., 'What are the new GST filing requirements for small businesses?'")
    if st.button("Ask") and query:
        agent = get_query_agent()
        with st.spinner("Searching..."):
            result = agent.answer(query, profile.model_dump())
        st.markdown(result["answer"])
        st.caption("Sources: " + ", ".join(set(result["citations"])))

with tab_graph:
    st.markdown("### Version Graph Explorer")
    st.info("Visual explorer for the regulatory version graph. Select a document to see its change history.")
    from core.version_graph import VersionGraph

    vg = VersionGraph()
    recent = vg.get_recent_changes(days=90)
    if recent:
        st.dataframe(
            [
                {
                    "Document": c.get("doc_id", ""),
                    "Change Type": c.get("change_type", ""),
                    "Severity": c.get("severity", ""),
                    "Summary": c.get("new_text_summary", "")[:120],
                }
                for c in recent
            ]
        )
    else:
        st.write("No changes recorded yet.")
