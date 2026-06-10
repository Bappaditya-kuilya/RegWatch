from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.query_agent import QueryAgent
from core.models import CompanyProfile
from graph.pipeline import build_pipeline
from scripts.seed_data import clean_runtime_data, run_local_versions

st.set_page_config(
    page_title="RegWatch",
    page_icon="RW",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

        :root {
          --bg-canvas: #0C0C0F;
          --bg-surface: #13131A;
          --bg-elevated: #1C1C26;
          --bg-overlay: #252535;
          --border-subtle: rgba(255,255,255,0.06);
          --border-default: rgba(255,255,255,0.10);
          --border-strong: rgba(255,255,255,0.18);
          --text-primary: #F0F0F4;
          --text-secondary: #8E8E9E;
          --text-tertiary: #5A5A6E;
          --text-inverse: #0C0C0F;
          --accent: #00C9A7;
          --accent-dim: rgba(0,201,167,0.12);
          --accent-border: rgba(0,201,167,0.30);
          --critical: #F87171;
          --critical-bg: rgba(248,113,113,0.10);
          --critical-border: rgba(248,113,113,0.25);
          --major: #FBBF24;
          --major-bg: rgba(251,191,36,0.10);
          --major-border: rgba(251,191,36,0.25);
          --minor: #60A5FA;
          --minor-bg: rgba(96,165,250,0.10);
          --minor-border: rgba(96,165,250,0.25);
          --success: #34D399;
          --success-bg: rgba(52,211,153,0.10);
          --success-border: rgba(52,211,153,0.25);
          --running: #A78BFA;
          --running-bg: rgba(167,139,250,0.10);
          --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
          --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
        }

        html, body, [class*="css"]  {
          font-family: var(--font-sans);
        }

        .stApp {
          background: var(--bg-canvas);
          color: var(--text-primary);
        }

        .main .block-container {
          max-width: 1180px;
          padding-top: 1.6rem;
          padding-bottom: 2rem;
        }

        section[data-testid="stSidebar"] {
          background: var(--bg-surface);
          border-right: 1px solid var(--border-subtle);
        }

        #MainMenu, footer, header {
          visibility: hidden;
        }

        .stMarkdown, .stText, .stCaption, p, li, div {
          color: var(--text-primary);
        }

        .stRadio label, .stSelectbox label, .stTextInput label {
          color: var(--text-secondary) !important;
        }

        .stButton > button {
          background: var(--accent);
          color: var(--text-inverse);
          border: 1px solid var(--accent);
          border-radius: 8px;
          height: 38px;
          font-size: 13px;
          font-weight: 500;
          transition: all 150ms ease;
        }

        .stButton > button:hover {
          background: #00b496;
          border-color: #00b496;
          transform: translateY(-1px);
        }

        .stButton > button:focus-visible {
          outline: 2px solid var(--accent);
          outline-offset: 2px;
        }

        .stTextInput > div > div > input {
          background: var(--bg-elevated);
          color: var(--text-primary);
          border: 1px solid var(--border-default);
          border-radius: 8px;
        }

        .stTextInput > div > div > input::placeholder {
          color: var(--text-tertiary);
        }

        .stTabs [data-baseweb="tab-list"] {
          background: transparent;
          border-bottom: 1px solid var(--border-subtle);
          gap: 0;
        }

        .stTabs [data-baseweb="tab"] {
          height: 44px;
          background: transparent;
          color: var(--text-secondary);
          padding-left: 0;
          padding-right: 20px;
        }

        .stTabs [aria-selected="true"] {
          color: var(--accent);
        }

        .stDataFrame, [data-testid="stDataFrame"] {
          border-radius: 12px;
          overflow: hidden;
          border: 1px solid var(--border-subtle);
          background: var(--bg-surface);
        }

        [data-testid="stMetric"] {
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-radius: 12px;
          padding: 14px 16px;
        }

        [data-testid="stMetricLabel"] {
          color: var(--text-tertiary);
        }

        [data-testid="stMetricValue"] {
          color: var(--text-primary);
        }

        .streamlit-expanderHeader {
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-radius: 8px;
        }

        .rw-topbar {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 24px;
          margin-bottom: 24px;
          padding: 24px;
          background: linear-gradient(180deg, rgba(19,19,26,1) 0%, rgba(17,17,24,1) 100%);
          border: 1px solid var(--border-subtle);
          border-radius: 16px;
          box-shadow: 0 12px 32px rgba(0,0,0,0.22);
        }

        .rw-topbar-title {
          font-size: 24px;
          line-height: 1.25;
          font-weight: 600;
          margin: 0 0 8px 0;
          color: var(--text-primary);
        }

        .rw-topbar-copy {
          font-size: 14px;
          line-height: 1.6;
          color: var(--text-secondary);
          max-width: 70ch;
          margin: 0;
        }

        .rw-panel {
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-radius: 12px;
          padding: 20px;
          box-shadow: 0 6px 18px rgba(0,0,0,0.16);
        }

        .rw-panel + .rw-panel {
          margin-top: 16px;
        }

        .rw-grid-4 {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 12px;
          margin: 24px 0 16px 0;
        }

        .rw-grid-2 {
          display: grid;
          grid-template-columns: minmax(0, 1.3fr) minmax(320px, 0.7fr);
          gap: 16px;
          align-items: start;
        }

        .rw-section-title {
          font-size: 16px;
          font-weight: 500;
          color: var(--text-primary);
          margin: 0 0 12px 0;
        }

        .rw-section-copy {
          font-size: 13px;
          color: var(--text-secondary);
          line-height: 1.5;
          margin: 0;
        }

        .rw-company {
          display: grid;
          gap: 12px;
        }

        .rw-company-row {
          padding: 10px 12px;
          border: 1px solid var(--border-subtle);
          border-radius: 8px;
          background: var(--bg-elevated);
        }

        .rw-company-label {
          font-size: 11px;
          color: var(--text-tertiary);
          margin-bottom: 4px;
          letter-spacing: 0.02em;
        }

        .rw-company-value {
          font-size: 13px;
          color: var(--text-primary);
          line-height: 1.4;
        }

        .rw-code {
          font-family: var(--font-mono);
        }

        .rw-source-list {
          display: grid;
          gap: 8px;
        }

        .rw-source-item {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          padding: 10px 12px;
          border-radius: 8px;
          background: var(--bg-elevated);
          border: 1px solid var(--border-subtle);
          font-size: 13px;
        }

        .rw-source-status {
          color: var(--success);
        }

        .rw-source-planned {
          color: var(--text-tertiary);
        }

        .rw-badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 3px 8px;
          border-radius: 999px;
          font-size: 11px;
          font-weight: 500;
          border: 1px solid transparent;
        }

        .rw-badge-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          flex-shrink: 0;
        }

        .rw-badge-critical {
          color: var(--critical);
          background: var(--critical-bg);
          border-color: var(--critical-border);
        }

        .rw-badge-critical .rw-badge-dot {
          background: var(--critical);
          animation: pulse-critical 2s ease-in-out infinite;
        }

        .rw-badge-major {
          color: var(--major);
          background: var(--major-bg);
          border-color: var(--major-border);
        }

        .rw-badge-major .rw-badge-dot {
          background: var(--major);
        }

        .rw-badge-minor {
          color: var(--minor);
          background: var(--minor-bg);
          border-color: var(--minor-border);
        }

        .rw-badge-minor .rw-badge-dot {
          background: var(--minor);
        }

        .rw-badge-success {
          color: var(--success);
          background: var(--success-bg);
          border-color: var(--success-border);
        }

        .rw-badge-success .rw-badge-dot {
          background: var(--success);
        }

        .rw-pipeline {
          display: grid;
          gap: 8px;
        }

        .rw-pipeline-status {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 10px 12px;
          background: var(--bg-elevated);
          border: 1px solid var(--border-subtle);
          border-radius: 8px;
          font-size: 13px;
        }

        .rw-pipeline-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          flex-shrink: 0;
        }

        .rw-pipeline-idle .rw-pipeline-dot {
          background: var(--text-tertiary);
        }

        .rw-pipeline-running .rw-pipeline-dot {
          background: var(--running);
          animation: pulse-running 1.2s ease-in-out infinite;
        }

        .rw-pipeline-complete .rw-pipeline-dot {
          background: var(--success);
        }

        .rw-pipeline-meta {
          margin-left: auto;
          color: var(--text-tertiary);
          font-size: 11px;
        }

        .rw-metric-card {
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-radius: 12px;
          padding: 20px;
          transition: border-color 180ms ease, transform 180ms ease;
        }

        .rw-metric-card:hover {
          border-color: var(--border-default);
          transform: translateY(-1px);
        }

        .rw-metric-label {
          font-size: 12px;
          color: var(--text-tertiary);
          margin-bottom: 8px;
        }

        .rw-metric-value {
          font-size: 32px;
          line-height: 1.2;
          font-weight: 600;
          color: var(--text-primary);
          font-variant-numeric: tabular-nums;
        }

        .rw-metric-meta {
          margin-top: 8px;
          font-size: 11px;
          color: var(--text-secondary);
        }

        .rw-task-card {
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-left-width: 3px;
          border-radius: 12px;
          padding: 20px;
          transition: transform 180ms ease, border-color 180ms ease;
        }

        .rw-task-card:hover {
          transform: translateY(-2px);
          border-color: var(--border-default);
        }

        .rw-task-critical { border-left-color: var(--critical); }
        .rw-task-major { border-left-color: var(--major); }
        .rw-task-minor { border-left-color: var(--minor); }

        .rw-task-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 12px;
        }

        .rw-task-title {
          margin: 0 0 10px 0;
          font-size: 16px;
          font-weight: 500;
          color: var(--text-primary);
          line-height: 1.3;
        }

        .rw-task-description {
          margin: 0 0 14px 0;
          font-size: 14px;
          line-height: 1.7;
          color: var(--text-secondary);
          max-width: 65ch;
        }

        .rw-task-deadline {
          font-size: 13px;
          color: var(--text-secondary);
        }

        .rw-task-deadline-urgent {
          color: var(--critical);
        }

        .rw-penalty {
          display: block;
          padding: 10px 12px;
          background: var(--critical-bg);
          border: 1px solid var(--critical-border);
          border-radius: 8px;
          color: var(--critical);
          font-size: 13px;
          line-height: 1.5;
          margin-bottom: 16px;
        }

        .rw-task-footer {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: center;
        }

        .rw-task-list {
          display: grid;
          gap: 12px;
        }

        .rw-group-title {
          font-size: 13px;
          font-weight: 500;
          color: var(--text-secondary);
          margin: 16px 0 12px 0;
        }

        .rw-citation {
          font-family: var(--font-mono);
          font-size: 12px;
          color: var(--text-tertiary);
        }

        .rw-change-row {
          display: grid;
          grid-template-columns: 104px 128px 1fr 156px 84px;
          gap: 16px;
          align-items: start;
          padding: 14px 16px;
          border-bottom: 1px solid var(--border-subtle);
        }

        .rw-change-row:last-child {
          border-bottom: none;
        }

        .rw-change-stack {
          display: grid;
          gap: 8px;
        }

        .rw-change-type {
          display: inline-flex;
          align-items: center;
          padding: 3px 8px;
          border-radius: 999px;
          background: var(--bg-overlay);
          color: var(--text-secondary);
          font-size: 11px;
          border: 1px solid var(--border-subtle);
        }

        .rw-change-new {
          margin: 0 0 4px 0;
          font-size: 13px;
          line-height: 1.5;
          color: var(--text-primary);
        }

        .rw-change-old {
          margin: 0;
          font-size: 11px;
          line-height: 1.5;
          color: var(--text-tertiary);
        }

        .rw-change-source {
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--accent);
        }

        .rw-change-date {
          display: block;
          font-family: var(--font-sans);
          color: var(--text-tertiary);
          margin-top: 4px;
        }

        .rw-confidence-track {
          height: 3px;
          background: var(--border-subtle);
          border-radius: 99px;
          margin: 4px 0;
        }

        .rw-confidence-fill {
          height: 100%;
          background: var(--accent);
          border-radius: 99px;
        }

        .rw-confidence-label {
          font-size: 11px;
          color: var(--text-tertiary);
        }

        .rw-message {
          background: var(--bg-elevated);
          border: 1px solid var(--border-subtle);
          border-radius: 12px;
          padding: 16px 20px;
          animation: item-appear 250ms cubic-bezier(0.16,1,0.3,1) both;
        }

        .rw-message-meta {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 10px;
        }

        .rw-message-intent {
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--accent);
          background: var(--accent-dim);
          border: 1px solid var(--accent-border);
          padding: 2px 8px;
          border-radius: 999px;
        }

        .rw-message-time {
          font-size: 11px;
          color: var(--text-tertiary);
        }

        .rw-message-body {
          font-size: 14px;
          line-height: 1.7;
          color: var(--text-primary);
        }

        .rw-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-top: 12px;
        }

        .rw-tag {
          font-family: var(--font-mono);
          font-size: 11px;
          color: var(--text-secondary);
          background: var(--bg-overlay);
          border: 1px solid var(--border-subtle);
          padding: 3px 8px;
          border-radius: 999px;
        }

        .rw-empty {
          padding: 18px 0;
          color: var(--text-secondary);
          font-size: 14px;
        }

        .rw-kv {
          display: grid;
          gap: 12px;
        }

        .rw-kv-row {
          display: flex;
          justify-content: space-between;
          gap: 16px;
          padding-bottom: 12px;
          border-bottom: 1px solid var(--border-subtle);
        }

        .rw-kv-row:last-child {
          padding-bottom: 0;
          border-bottom: none;
        }

        .rw-kv-label {
          font-size: 12px;
          color: var(--text-tertiary);
        }

        .rw-kv-value {
          font-size: 13px;
          color: var(--text-primary);
          text-align: right;
          max-width: 55%;
        }

        .rw-history-list {
          display: grid;
          gap: 12px;
        }

        .rw-history-item {
          padding: 16px;
          background: var(--bg-surface);
          border: 1px solid var(--border-subtle);
          border-radius: 12px;
        }

        .rw-history-head {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 8px;
        }

        .rw-history-doc {
          font-family: var(--font-mono);
          font-size: 12px;
          color: var(--accent);
        }

        .rw-history-summary {
          margin: 0;
          font-size: 14px;
          line-height: 1.6;
          color: var(--text-primary);
          max-width: 70ch;
        }

        .rw-history-meta {
          margin-top: 8px;
          font-size: 12px;
          color: var(--text-tertiary);
        }

        @keyframes pulse-critical {
          0%, 100% { opacity: 1; transform: scale(1); box-shadow: 0 0 0 0 rgba(248,113,113,0.4); }
          50% { opacity: 0.7; transform: scale(0.9); box-shadow: 0 0 0 4px rgba(248,113,113,0); }
        }

        @keyframes pulse-running {
          0%, 100% { box-shadow: 0 0 0 0 rgba(167,139,250,0.5); }
          50% { box-shadow: 0 0 0 6px rgba(167,139,250,0); }
        }

        @keyframes item-appear {
          from { opacity: 0; transform: translateY(6px); }
          to { opacity: 1; transform: translateY(0); }
        }

        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after {
            animation-duration: 0.01ms !important;
            transition-duration: 0.01ms !important;
          }
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
    st.session_state.setdefault("last_run_mode", "Regulatory Corpus")
    st.session_state.setdefault("last_query_result", None)


RUN_MODE_OPTIONS = [
    "Controlled Review",
    "Regulatory Corpus",
    "Live Source Check",
]

RUN_MODE_HELP = {
    "Controlled Review": "Uses the controlled fixture set for deterministic review and presentation.",
    "Regulatory Corpus": "Runs against the seeded corpus already available in the local registry.",
    "Live Source Check": "Polls live sources and should be used only outside presentation scenarios.",
}


def get_seeded_demo_doc_ids() -> list[str]:
    db_path = Path("data/registry.db")
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("select doc_id from documents where doc_id = 'DEMO_NAMKEEN_NOTICE'").fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def get_all_seeded_doc_ids() -> list[str]:
    db_path = Path("data/registry.db")
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("select doc_id from documents order by doc_id").fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def ensure_demo_seeded() -> list[str]:
    existing = get_seeded_demo_doc_ids()
    if existing:
        return existing
    Path("data").mkdir(parents=True, exist_ok=True)
    run_local_versions(Path("tests/fixtures/demo_manifest.json"))
    return get_seeded_demo_doc_ids()


def title_case(value: str) -> str:
    return value.replace("_", " ").title()


def priority_label(priority: int) -> str:
    return f"Priority {priority}"


def dedupe_by_attr(items: list[Any], attr: str) -> list[Any]:
    seen: set[str] = set()
    deduped: list[Any] = []
    for item in items:
        value = getattr(item, attr, None)
        if value is None:
            deduped.append(item)
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result)
    normalized["detected_changes"] = dedupe_by_attr(result.get("detected_changes", []), "change_id")
    normalized["impact_assessments"] = dedupe_by_attr(result.get("impact_assessments", []), "change_id")
    normalized["action_plan"] = dedupe_by_attr(result.get("action_plan", []), "task_id")
    normalized["action_plan"] = sorted(normalized["action_plan"], key=lambda task: task.priority)
    return normalized


def severity_badge(severity: str) -> str:
    normalized = severity.lower()
    if normalized == "critical":
        klass = "rw-badge rw-badge-critical"
    elif normalized == "major":
        klass = "rw-badge rw-badge-major"
    elif normalized == "success":
        klass = "rw-badge rw-badge-success"
    else:
        klass = "rw-badge rw-badge-minor"
    return (
        f'<span class="{klass}">'
        f'<span class="rw-badge-dot"></span>{title_case(normalized)}</span>'
    )


def pipeline_status_html(result: dict[str, Any], run_mode: str, last_run_at: str | None) -> str:
    if not result:
        return (
            '<div class="rw-pipeline rw-panel">'
            '<div class="rw-section-title">Pipeline</div>'
            '<div class="rw-pipeline-status rw-pipeline-idle">'
            '<span class="rw-pipeline-dot"></span>'
            '<span>Idle</span>'
            '<span class="rw-pipeline-meta">No run yet</span>'
            '</div></div>'
        )
    changes = len(result.get("detected_changes", []))
    tasks = len(result.get("action_plan", []))
    return (
        '<div class="rw-pipeline rw-panel">'
        '<div class="rw-section-title">Pipeline</div>'
        '<div class="rw-pipeline-status rw-pipeline-complete">'
        '<span class="rw-pipeline-dot"></span>'
        '<span>Complete</span>'
        f'<span class="rw-pipeline-meta">{changes} changes, {tasks} tasks</span>'
        '</div>'
        f'<div class="rw-section-copy">Mode: {run_mode} | Last run: {last_run_at or "Unknown"}</div>'
        "</div>"
    )


def format_run_mode_label(run_mode: str) -> str:
    if run_mode == "Demo Mode":
        return "Controlled Review"
    if run_mode == "Live Scrape":
        return "Live Source Check"
    return run_mode


def render_sidebar(profile: CompanyProfile, result: dict[str, Any], last_run_mode: str, last_run_at: str | None) -> str:
    with st.sidebar:
        st.markdown('<div class="rw-section-title">RegWatch</div>', unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="rw-panel">
              <div class="rw-section-title">Company</div>
              <div class="rw-company">
                <div class="rw-company-row">
                  <div class="rw-company-label">Tenant</div>
                  <div class="rw-company-value">{profile.company_name}</div>
                </div>
                <div class="rw-company-row">
                  <div class="rw-company-label">Business Type</div>
                  <div class="rw-company-value">{profile.business_type}</div>
                </div>
                <div class="rw-company-row">
                  <div class="rw-company-label">GSTIN</div>
                  <div class="rw-company-value rw-code">{profile.gstin or "Not configured"}</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        current_mode = format_run_mode_label(last_run_mode)
        st.markdown(pipeline_status_html(result, current_mode, last_run_at), unsafe_allow_html=True)
        run_mode = st.radio(
            "Execution Mode",
            RUN_MODE_OPTIONS,
            index=RUN_MODE_OPTIONS.index(current_mode) if current_mode in RUN_MODE_OPTIONS else 1,
            help=RUN_MODE_HELP[current_mode] if current_mode in RUN_MODE_HELP else RUN_MODE_HELP["Regulatory Corpus"],
        )
        st.markdown(
            """
            <div class="rw-panel">
              <div class="rw-section-title">Data Sources</div>
              <div class="rw-source-list">
                <div class="rw-source-item"><span>GST Circulars</span><span class="rw-source-status">Enabled</span></div>
                <div class="rw-source-item"><span>MCA Notifications</span><span class="rw-source-status">Enabled</span></div>
                <div class="rw-source-item"><span>FSSAI Orders</span><span class="rw-source-status">Enabled</span></div>
                <div class="rw-source-item"><span>eGazette</span><span class="rw-source-planned">Planned</span></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    return run_mode


def run_pipeline_for_mode(profile: CompanyProfile, run_mode: str) -> dict[str, Any]:
    pipeline = get_pipeline()
    if run_mode == "Controlled Review":
        trigger = "seeded"
        doc_ids = ensure_demo_seeded()
    elif run_mode == "Regulatory Corpus":
        trigger = "seeded"
        doc_ids = get_all_seeded_doc_ids()
    else:
        trigger = "manual"
        doc_ids = []
    result = pipeline.invoke(
        {
            "trigger": trigger,
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
            "run_mode": run_mode,
        },
        config={"configurable": {"thread_id": f"streamlit-{run_mode.lower().replace(' ', '-')}" }},
    )
    return normalize_result(result)


def render_header(profile: CompanyProfile) -> None:
    st.markdown(
        f"""
        <div class="rw-topbar">
          <div>
            <h1 class="rw-topbar-title">RegWatch Compliance Operations</h1>
            <p class="rw-topbar-copy">
              Monitor regulatory version changes, assess applicability for {profile.company_name},
              and convert detected amendments into an auditable compliance queue.
            </p>
          </div>
          <div class="rw-code" style="font-size:12px;color:var(--text-tertiary);">
            {profile.state} | {profile.business_type}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metrics(result: dict[str, Any], run_mode: str, last_run_at: str | None) -> None:
    changes = result.get("detected_changes", [])
    tasks = result.get("action_plan", [])
    assessments = result.get("impact_assessments", [])
    applicable = sum(1 for item in assessments if getattr(item, "is_applicable", False))
    critical = sum(1 for task in tasks if getattr(task, "priority", 5) == 1)
    st.markdown(
        f"""
        <div class="rw-grid-4">
          <div class="rw-metric-card">
            <div class="rw-metric-label">Changes detected</div>
            <div class="rw-metric-value">{len(changes)}</div>
            <div class="rw-metric-meta">Current execution scope</div>
          </div>
          <div class="rw-metric-card">
            <div class="rw-metric-label">Applicable changes</div>
            <div class="rw-metric-value">{applicable}</div>
            <div class="rw-metric-meta">Matched to company profile</div>
          </div>
          <div class="rw-metric-card">
            <div class="rw-metric-label">Compliance tasks</div>
            <div class="rw-metric-value">{len(tasks)}</div>
            <div class="rw-metric-meta">Open operational actions</div>
          </div>
          <div class="rw-metric-card" style="border-left:3px solid var(--critical);">
            <div class="rw-metric-label">Critical tasks</div>
            <div class="rw-metric-value">{critical}</div>
            <div class="rw-metric-meta">Priority 1 obligations</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if last_run_at:
        st.caption(f"Last execution: {last_run_at} | Mode: {format_run_mode_label(run_mode)}")
    if result.get("errors"):
        st.error("\n".join(result["errors"]))


def render_change_register(changes: list[Any]) -> None:
    st.markdown('<div class="rw-section-title">Change Register</div>', unsafe_allow_html=True)
    if not changes:
        st.markdown('<div class="rw-empty">No changes detected in the current run.</div>', unsafe_allow_html=True)
        return
    st.markdown('<div class="rw-panel" style="padding:0;">', unsafe_allow_html=True)
    for change in changes:
        confidence = int(change.confidence * 100)
        st.markdown(
            f"""
            <div class="rw-change-row">
              <div>{severity_badge(change.severity.value)}</div>
              <div><span class="rw-change-type">{title_case(change.change_type.value)}</span></div>
              <div>
                <div class="rw-change-stack">
                  <p class="rw-change-new">{escape(change.new_text_summary)}</p>
                  <p class="rw-change-old">Previously: {escape(change.old_text_summary)}</p>
                </div>
              </div>
              <div>
                <span class="rw-change-source">{escape(change.doc_id)}</span>
                <span class="rw-change-date">{escape(change.new_version)}</span>
              </div>
              <div>
                <div class="rw-confidence-track"><div class="rw-confidence-fill" style="width:{confidence}%"></div></div>
                <span class="rw-confidence-label">{confidence}%</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def render_dashboard(result: dict[str, Any]) -> None:
    tasks = result.get("action_plan", [])
    changes = result.get("detected_changes", [])
    assessments = result.get("impact_assessments", [])
    applicable = sum(1 for item in assessments if getattr(item, "is_applicable", False))
    critical_tasks = [task for task in tasks if getattr(task, "priority", 5) == 1]
    spotlight_tasks = critical_tasks[:1] or tasks[:1]

    left_column, right_column = st.columns([1.3, 0.7])
    with left_column:
        st.markdown(
            """
            <div class="rw-panel">
              <div class="rw-section-title">Requires Action</div>
              <p class="rw-section-copy">Highest-priority obligations surfaced from the latest pipeline execution.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if spotlight_tasks:
            for task in spotlight_tasks:
                render_task_card(task)
        else:
            st.markdown('<div class="rw-empty">No priority tasks are available for the current execution.</div>', unsafe_allow_html=True)
    with right_column:
        latest_change = changes[0] if changes else None
        st.markdown(
            """
            <div class="rw-panel">
              <div class="rw-section-title">Run Snapshot</div>
              <div class="rw-kv">
            """,
            unsafe_allow_html=True,
        )
        snapshot_rows = [
            ("Detected changes", str(len(changes))),
            ("Applicable assessments", str(applicable)),
            ("Open tasks", str(len(tasks))),
            ("Latest source", getattr(latest_change, "doc_id", "No recent document")),
        ]
        for label, value in snapshot_rows:
            st.markdown(
                f"""
                <div class="rw-kv-row">
                  <span class="rw-kv-label">{escape(label)}</span>
                  <span class="rw-kv-value">{escape(value)}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown("</div></div>", unsafe_allow_html=True)

    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)
    render_change_register(changes[:5])


def render_task_card(task: Any) -> None:
    severity = "minor"
    if task.priority == 1:
        severity = "critical"
    elif task.priority in (2, 3):
        severity = "major"
    deadline = task.deadline.strftime("%d %b %Y") if task.deadline else "No fixed date"
    deadline_class = "rw-task-deadline"
    if task.deadline and (task.deadline - datetime.now()).days < 30:
        deadline_class += " rw-task-deadline-urgent"
    penalty_html = ""
    if task.penalty_if_missed:
        penalty_html = f"<div class='rw-penalty'>Penalty: {escape(task.penalty_if_missed)}</div>"
    st.markdown(
        f"""
        <div class="rw-task-card rw-task-{severity}">
          <div class="rw-task-header">
            {severity_badge(severity)}
            <span class="{deadline_class}">{deadline}</span>
          </div>
          <h3 class="rw-task-title">{escape(task.title)}</h3>
          <p class="rw-task-description">{escape(task.description)}</p>
          {penalty_html}
          <div class="rw-task-footer">
            <span class="rw-citation">{escape(task.citation)}</span>
            <span class="rw-citation">{escape(task.status.title())}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_tasks(tasks: list[Any]) -> None:
    st.markdown('<div class="rw-section-title">Compliance Queue</div>', unsafe_allow_html=True)
    if not tasks:
        st.markdown('<div class="rw-empty">No compliance tasks are available for the current run.</div>', unsafe_allow_html=True)
        return
    pending = [task for task in tasks if getattr(task, "status", "") == "pending"]
    acknowledged = [task for task in tasks if getattr(task, "status", "") == "acknowledged"]
    completed = [task for task in tasks if getattr(task, "status", "") == "completed"]
    st.markdown(
        f"""
        <div class="rw-panel">
          <div class="rw-section-copy">
            Pending {len(pending)} | Acknowledged {len(acknowledged)} | Completed {len(completed)}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    grouped = [
        ("Critical", [task for task in tasks if getattr(task, "priority", 5) == 1]),
        ("Major", [task for task in tasks if getattr(task, "priority", 5) in (2, 3)]),
        ("Minor", [task for task in tasks if getattr(task, "priority", 5) >= 4]),
    ]
    for label, group_tasks in grouped:
        if not group_tasks:
            continue
        st.markdown(f'<div class="rw-group-title">{label}</div>', unsafe_allow_html=True)
        st.markdown('<div class="rw-task-list">', unsafe_allow_html=True)
        for task in group_tasks:
            render_task_card(task)
        st.markdown("</div>", unsafe_allow_html=True)


def render_assistant(profile: CompanyProfile) -> None:
    st.markdown('<div class="rw-section-title">Ask RegWatch</div>', unsafe_allow_html=True)
    query = st.text_input(
        "Ask about any regulation, deadline, change, or business impact.",
        placeholder="What changed in branded packaged namkeen compliance requirements?",
    )
    if st.button("Ask", key="assistant_ask"):
        if query:
            with st.spinner("Resolving query..."):
                st.session_state["last_query_result"] = get_query_agent().answer(query, profile.model_dump())
    result = st.session_state.get("last_query_result")
    if result:
        current_time = datetime.now().strftime("%H:%M")
        citations = "".join(
            f'<span class="rw-tag">{escape(citation)}</span>'
            for citation in sorted(set(result.get("citations", [])))
            if citation
        )
        st.markdown(
            f"""
            <div class="rw-message">
              <div class="rw-message-meta">
                <span class="rw-message-intent">{escape(result.get("query_type", "unknown"))}</span>
                <span class="rw-message-time">{current_time}</span>
              </div>
              <div class="rw-message-body">{escape(result["answer"])}</div>
              <div class="rw-tags">{citations}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_version_history() -> None:
    from core.version_graph import VersionGraph

    st.markdown('<div class="rw-section-title">Version History</div>', unsafe_allow_html=True)
    recent = VersionGraph().get_recent_changes(days=90)
    if not recent:
        st.markdown('<div class="rw-empty">No recorded version history is available yet.</div>', unsafe_allow_html=True)
        return
    st.markdown('<div class="rw-history-list">', unsafe_allow_html=True)
    for item in recent[:12]:
        st.markdown(
            f"""
            <div class="rw-history-item">
              <div class="rw-history-head">
                <span class="rw-history-doc">{escape(str(item.get("doc_id", "")))}</span>
                {severity_badge(str(item.get("severity", "minor")))}
              </div>
              <p class="rw-history-summary">{escape(str(item.get("new_text_summary", "")))}</p>
              <div class="rw-history-meta">
                {escape(title_case(str(item.get("change_type", ""))))} | {escape(str(item.get("new_version", "Unknown version")))}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    inject_css()
    init_session_state()
    profile = load_profile()
    render_header(profile)
    result = normalize_result(st.session_state.get("last_result", {}))
    run_mode = render_sidebar(
        profile,
        result,
        st.session_state["last_run_mode"],
        st.session_state["last_run_at"],
    )

    control_left, control_right = st.columns([1.5, 1])
    with control_left:
        st.markdown(
            """
            <div class="rw-panel">
              <div class="rw-section-title">Operator Run Control</div>
              <p class="rw-section-copy">
                Execute the pipeline against the selected source mode. Controlled Review is the stable path for rehearsals and external walkthroughs.
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with control_right:
        if st.button("Run Pipeline", use_container_width=False):
            with st.spinner("Executing pipeline..."):
                st.session_state["last_result"] = run_pipeline_for_mode(profile, run_mode)
                st.session_state["last_run_mode"] = run_mode
                st.session_state["last_run_at"] = datetime.now().strftime("%d %b %Y %H:%M")
            st.success("Pipeline execution complete.")

    result = normalize_result(st.session_state.get("last_result", {}))
    render_metrics(result, st.session_state["last_run_mode"], st.session_state["last_run_at"])

    tab_dashboard, tab_changes, tab_tasks, tab_assistant, tab_history = st.tabs(
        ["Dashboard", "Change Register", "Compliance Queue", "Ask RegWatch", "Version History"]
    )
    with tab_dashboard:
        render_dashboard(result)
    with tab_changes:
        render_change_register(result.get("detected_changes", []))
    with tab_tasks:
        render_tasks(result.get("action_plan", []))
    with tab_assistant:
        render_assistant(profile)
    with tab_history:
        render_version_history()


main()
