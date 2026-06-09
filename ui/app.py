from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.query_agent import QueryAgent
from core.models import CompanyProfile
from graph.pipeline import build_pipeline

st.set_page_config(
    page_title="RegWatch",
    page_icon="RW",
    layout="wide",
    initial_sidebar_state="expanded",
)


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
          --bg: #f5f7fb;
          --panel: #ffffff;
          --line: #d8dee9;
          --text: #132033;
          --muted: #5f6b7a;
          --brand: #12355b;
          --brand-soft: #e9f0f7;
          --accent: #9a3412;
          --critical: #b42318;
          --major: #b54708;
          --minor: #475467;
          --success: #067647;
        }
        .stApp {
          background: linear-gradient(180deg, #f8fafc 0%, #eef3f8 100%);
        }
        .block-container {
          padding-top: 1.5rem;
          padding-bottom: 2rem;
        }
        .rw-hero {
          background: linear-gradient(135deg, #0f2742 0%, #163a63 100%);
          color: #f8fbff;
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 18px;
          padding: 1.4rem 1.6rem;
          margin-bottom: 1rem;
          box-shadow: 0 16px 40px rgba(10, 27, 49, 0.18);
        }
        .rw-hero-title {
          font-size: 1.6rem;
          font-weight: 700;
          margin-bottom: 0.3rem;
          letter-spacing: -0.02em;
        }
        .rw-hero-subtitle {
          color: rgba(248, 251, 255, 0.82);
          font-size: 0.96rem;
          line-height: 1.5;
        }
        .rw-card {
          background: var(--panel);
          border: 1px solid var(--line);
          border-radius: 16px;
          padding: 1rem 1.1rem;
          box-shadow: 0 8px 24px rgba(16, 24, 40, 0.05);
          margin-bottom: 1rem;
        }
        .rw-card h4 {
          margin: 0 0 0.65rem 0;
          color: var(--text);
          font-size: 0.95rem;
          letter-spacing: 0.01em;
        }
        .rw-metric-label {
          color: var(--muted);
          font-size: 0.78rem;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }
        .rw-metric-value {
          color: var(--text);
          font-size: 1.7rem;
          font-weight: 700;
          margin-top: 0.18rem;
        }
        .rw-inline-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 0.6rem;
        }
        .rw-inline-item {
          border: 1px solid var(--line);
          border-radius: 12px;
          padding: 0.7rem 0.8rem;
          background: #fbfcfe;
        }
        .rw-inline-item .label {
          font-size: 0.74rem;
          color: var(--muted);
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }
        .rw-inline-item .value {
          font-size: 0.95rem;
          color: var(--text);
          margin-top: 0.18rem;
          font-weight: 600;
        }
        .rw-status {
          display: inline-block;
          border-radius: 999px;
          padding: 0.24rem 0.65rem;
          font-size: 0.75rem;
          font-weight: 700;
          letter-spacing: 0.03em;
          border: 1px solid transparent;
        }
        .rw-status-critical {
          color: var(--critical);
          background: #fef3f2;
          border-color: #fecdca;
        }
        .rw-status-major {
          color: var(--major);
          background: #fff7ed;
          border-color: #fed7aa;
        }
        .rw-status-minor {
          color: var(--minor);
          background: #f8fafc;
          border-color: #d0d5dd;
        }
        .rw-status-success {
          color: var(--success);
          background: #ecfdf3;
          border-color: #abefc6;
        }
        .rw-caption {
          color: var(--muted);
          font-size: 0.84rem;
          line-height: 1.45;
        }
        .rw-section-title {
          font-size: 1.02rem;
          font-weight: 700;
          color: var(--text);
          margin-bottom: 0.65rem;
        }
        .rw-sidebar-note {
          color: var(--muted);
          font-size: 0.84rem;
          line-height: 1.5;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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


def init_session_state() -> None:
    st.session_state.setdefault("last_result", {})
    st.session_state.setdefault("last_run_at", None)
    st.session_state.setdefault("last_run_mode", "Demo Mode")
    st.session_state.setdefault("last_query_result", None)


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


def format_severity(severity: str) -> str:
    return severity.replace("_", " ").title()


def severity_class(severity: str) -> str:
    if severity == "critical":
        return "rw-status rw-status-critical"
    if severity == "major":
        return "rw-status rw-status-major"
    return "rw-status rw-status-minor"


def priority_label(priority: int) -> str:
    mapping = {
        1: "Priority 1",
        2: "Priority 2",
        3: "Priority 3",
        4: "Priority 4",
        5: "Priority 5",
    }
    return mapping.get(priority, f"Priority {priority}")


def serialize_changes(changes: list[Any]) -> pd.DataFrame:
    rows = []
    for change in changes:
        rows.append(
            {
                "Document": change.doc_id,
                "Type": format_severity(change.change_type.value),
                "Severity": format_severity(change.severity.value),
                "Current Summary": change.new_text_summary,
                "Previous Summary": change.old_text_summary,
                "Confidence": f"{change.confidence:.0%}",
            }
        )
    return pd.DataFrame(rows)


def serialize_tasks(tasks: list[Any]) -> pd.DataFrame:
    rows = []
    for task in tasks:
        rows.append(
            {
                "Priority": priority_label(task.priority),
                "Title": task.title,
                "Status": task.status.title(),
                "Deadline": task.deadline.strftime("%d %b %Y") if task.deadline else "No fixed date",
                "Citation": task.citation,
            }
        )
    return pd.DataFrame(rows)


def render_header(profile: CompanyProfile) -> None:
    st.markdown(
        f"""
        <div class="rw-hero">
          <div class="rw-hero-title">RegWatch Control Center</div>
          <div class="rw-hero-subtitle">
            Version-aware regulatory monitoring for {profile.company_name}. Track document change history,
            applicability, and operational actions through a single review surface.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(label: str, value: str, caption: str = "") -> None:
    st.markdown(
        f"""
        <div class="rw-card">
          <div class="rw-metric-label">{label}</div>
          <div class="rw-metric-value">{value}</div>
          <div class="rw-caption">{caption}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar(profile: CompanyProfile) -> str:
    with st.sidebar:
        st.markdown("## Workspace")
        st.markdown(
            f"""
            <div class="rw-card">
              <h4>Tenant Profile</h4>
              <div class="rw-inline-grid">
                <div class="rw-inline-item">
                  <div class="label">Company</div>
                  <div class="value">{profile.company_name}</div>
                </div>
                <div class="rw-inline-item">
                  <div class="label">State</div>
                  <div class="value">{profile.state}</div>
                </div>
                <div class="rw-inline-item">
                  <div class="label">Business Type</div>
                  <div class="value">{profile.business_type}</div>
                </div>
                <div class="rw-inline-item">
                  <div class="label">Turnover</div>
                  <div class="value">{profile.annual_turnover_range}</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        run_mode = st.radio(
            "Execution Mode",
            ["Demo Mode", "Seeded Dataset", "Live Scrape"],
            help="Demo Mode runs the controlled version-history scenario. Seeded Dataset uses all ingested documents. Live Scrape fetches fresh source data.",
        )

        st.markdown(
            """
            <div class="rw-card">
              <h4>Source Coverage</h4>
              <div class="rw-inline-grid">
                <div class="rw-inline-item">
                  <div class="label">GST</div>
                  <div class="value">Enabled</div>
                </div>
                <div class="rw-inline-item">
                  <div class="label">MCA</div>
                  <div class="value">Enabled</div>
                </div>
                <div class="rw-inline-item">
                  <div class="label">FSSAI</div>
                  <div class="value">Enabled</div>
                </div>
                <div class="rw-inline-item">
                  <div class="label">eGazette</div>
                  <div class="value">Planned</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            """
            <div class="rw-sidebar-note">
              Demo Mode is the recommended operator path for reviewing the controlled version-aware scenario.
              Live Scrape remains available for source acquisition and ingestion checks.
            </div>
            """,
            unsafe_allow_html=True,
        )

    return run_mode


def run_pipeline_for_mode(profile: CompanyProfile, run_mode: str) -> dict[str, Any]:
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

    return pipeline.invoke(
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
        config={"configurable": {"thread_id": f"streamlit-{run_mode.lower().replace(' ', '-')}" }},
    )


def render_overview(result: dict[str, Any], run_mode: str, last_run_at: str | None) -> None:
    changes = result.get("detected_changes", [])
    tasks = result.get("action_plan", [])
    assessments = result.get("impact_assessments", [])
    applicable = sum(1 for a in assessments if getattr(a, "is_applicable", False))
    review_flag = "Required" if result.get("human_review_needed") else "Not required"

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_metric_card("Detected Changes", str(len(changes)), f"Run mode: {run_mode}")
    with col2:
        render_metric_card("Applicable Changes", str(applicable), "Changes mapped to tenant operations")
    with col3:
        render_metric_card("Open Tasks", str(len(tasks)), "Compliance actions prepared")
    with col4:
        render_metric_card("Human Review", review_flag, f"Last run: {last_run_at or 'Not run yet'}")

    if result.get("errors"):
        st.error("\n".join(result["errors"]))


def render_dashboard_tab(result: dict[str, Any]) -> None:
    changes = result.get("detected_changes", [])
    assessments = result.get("impact_assessments", [])

    left, right = st.columns([1.45, 1], gap="large")
    with left:
        st.markdown('<div class="rw-section-title">Change Register</div>', unsafe_allow_html=True)
        if not changes:
            st.info("No changes available. Run the pipeline to populate the register.")
        else:
            st.dataframe(serialize_changes(changes), use_container_width=True, hide_index=True)
            for change in changes:
                st.markdown(
                    f'<div class="{severity_class(change.severity.value)}">{format_severity(change.severity.value)}</div>',
                    unsafe_allow_html=True,
                )
                with st.expander(f"{change.doc_id} | {change.change_type.value.replace('_', ' ').title()}"):
                    st.write(change.new_text_summary)
                    st.caption(f"Previous state: {change.old_text_summary}")
                    st.caption(f"Affected clauses: {', '.join(change.affected_clauses) or 'Not identified'}")
                    st.caption(f"Confidence: {change.confidence:.0%}")

    with right:
        st.markdown('<div class="rw-section-title">Applicability Review</div>', unsafe_allow_html=True)
        if not assessments:
            st.info("Applicability assessments will appear here after a pipeline run.")
        else:
            for assessment in assessments:
                badge = severity_class(assessment.risk_level.value)
                st.markdown(
                    f"""
                    <div class="rw-card">
                      <div style="display:flex; justify-content:space-between; align-items:center; gap:1rem;">
                        <h4>{assessment.change_id}</h4>
                        <span class="{badge}">{format_severity(assessment.risk_level.value)}</span>
                      </div>
                      <div class="rw-caption">{assessment.applicability_reason}</div>
                      <div class="rw-caption" style="margin-top:0.55rem;">
                        Operations: {', '.join(assessment.affected_operations) or 'Not specified'}
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def render_tasks_tab(result: dict[str, Any]) -> None:
    tasks = result.get("action_plan", [])
    st.markdown('<div class="rw-section-title">Compliance Work Queue</div>', unsafe_allow_html=True)
    if not tasks:
        st.info("No tasks are available for the current run.")
        return

    st.dataframe(serialize_tasks(tasks), use_container_width=True, hide_index=True)
    for task in tasks:
        with st.expander(f"{priority_label(task.priority)} | {task.title}"):
            st.write(task.description)
            st.caption(f"Source: {task.citation}")
            st.caption(f"Status: {task.status.title()}")
            if task.deadline_source:
                st.caption(f"Deadline source: {task.deadline_source}")
            if task.penalty_if_missed:
                st.caption(f"Penalty context: {task.penalty_if_missed}")


def render_query_tab(profile: CompanyProfile) -> None:
    st.markdown('<div class="rw-section-title">Regulatory Assistant</div>', unsafe_allow_html=True)
    query = st.text_input(
        "Ask a question about the current regulatory position, recent changes, business impact, or required actions.",
        placeholder="What changed in branded packaged namkeen compliance requirements?",
    )
    if st.button("Run Query", use_container_width=False) and query:
        agent = get_query_agent()
        with st.spinner("Resolving query against the active knowledge base..."):
            st.session_state["last_query_result"] = agent.answer(query, profile.model_dump())

    result = st.session_state.get("last_query_result")
    if result:
        st.markdown(
            f"""
            <div class="rw-card">
              <h4>Assistant Response</h4>
              <div class="rw-caption">Route: {result.get("query_type", "unknown")}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write(result["answer"])
        citations = ", ".join(sorted(set(result.get("citations", []))))
        if citations:
            st.caption(f"Sources: {citations}")


def render_graph_tab() -> None:
    from core.version_graph import VersionGraph

    st.markdown('<div class="rw-section-title">Version History</div>', unsafe_allow_html=True)
    vg = VersionGraph()
    recent = vg.get_recent_changes(days=90)
    if not recent:
        st.info("No version history is available yet.")
        return

    rows = []
    for change in recent:
        rows.append(
            {
                "Document": change.get("doc_id", ""),
                "Severity": format_severity(str(change.get("severity", "minor"))),
                "Type": str(change.get("change_type", "")).replace("_", " ").title(),
                "Summary": str(change.get("new_text_summary", ""))[:160],
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def main() -> None:
    apply_theme()
    init_session_state()
    profile = load_profile()
    render_header(profile)
    run_mode = render_sidebar(profile)

    primary_col, secondary_col = st.columns([1.45, 0.85], gap="large")
    with primary_col:
        st.markdown(
            """
            <div class="rw-card">
              <h4>Execution Control</h4>
              <div class="rw-caption">
                Run the pipeline against the selected execution mode. Demo Mode is the recommended production-style review path for controlled validation and stakeholder demos.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with secondary_col:
        if st.button("Run Pipeline", type="primary", use_container_width=True):
            with st.spinner("Executing pipeline..."):
                st.session_state["last_result"] = run_pipeline_for_mode(profile, run_mode)
                st.session_state["last_run_mode"] = run_mode
                st.session_state["last_run_at"] = datetime.now().strftime("%d %b %Y %H:%M")
            st.success("Pipeline execution complete.")

    result = st.session_state.get("last_result", {})
    render_overview(result, st.session_state["last_run_mode"], st.session_state["last_run_at"])

    tab_dashboard, tab_tasks, tab_query, tab_graph = st.tabs(
        ["Overview", "Tasks", "Assistant", "Version History"]
    )

    with tab_dashboard:
        render_dashboard_tab(result)

    with tab_tasks:
        render_tasks_tab(result)

    with tab_query:
        render_query_tab(profile)

    with tab_graph:
        render_graph_tab()


main()
