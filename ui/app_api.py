"""RegWatch operator console — multi-tenant Streamlit frontend over the FastAPI backend.

Holds no pipeline/state logic: every action is an API call carrying the tenant's bearer
token (see ui/api_client.py). Run the backend separately:
    uvicorn api.main:app --port 8000
    streamlit run ui/app_api.py
Set REGWATCH_API_URL to point at a deployed backend (default http://localhost:8000).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import streamlit as st

from ui.api_client import RegWatchAPI, RegWatchAPIError

API_BASE = os.environ.get("REGWATCH_API_URL", "http://localhost:8000")
ROOT = Path(__file__).resolve().parents[1]

st.set_page_config(page_title="RegWatch Compliance Operations", layout="wide")

st.markdown(
    """
    <style>
      .rw-card{background:#11161d;border:1px solid #232c38;border-radius:10px;padding:14px 16px;margin-bottom:10px;}
      .rw-pri{font-size:12px;font-weight:700;letter-spacing:.04em;color:#9fb3c8;}
      .rw-title{font-size:16px;font-weight:650;color:#e7eef6;margin:2px 0 4px;}
      .rw-meta{font-size:12px;color:#8aa0b4;}
    </style>
    """,
    unsafe_allow_html=True,
)


def api() -> RegWatchAPI:
    return RegWatchAPI(API_BASE, token=st.session_state.get("token"))


# ── auth gate ────────────────────────────────────────────────────────────────

def render_auth() -> None:
    st.title("RegWatch Compliance Operations")
    st.caption("Version-aware regulatory change intelligence")
    login_tab, register_tab = st.tabs(["Sign in", "Register company"])

    with login_tab:
        with st.form("login"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in", type="primary"):
                try:
                    client = RegWatchAPI(API_BASE)
                    st.session_state.token = client.login(email, password)
                    st.session_state.email = email
                    st.rerun()
                except RegWatchAPIError as exc:
                    st.error(f"Login failed — {exc.detail}")

    with register_tab:
        with st.form("register"):
            company = st.text_input("Company name")
            email = st.text_input("Work email", key="reg_email")
            password = st.text_input("Password", type="password", key="reg_pw")
            if st.form_submit_button("Create account", type="primary"):
                try:
                    client = RegWatchAPI(API_BASE)
                    client.register(email, password, company)
                    st.session_state.token = client.login(email, password)
                    st.session_state.email = email
                    st.success("Account created.")
                    st.rerun()
                except RegWatchAPIError as exc:
                    st.error(f"Registration failed — {exc.detail}")


# ── profile ──────────────────────────────────────────────────────────────────

def render_profile(tenant: dict) -> None:
    st.subheader("Company profile")
    current = tenant.get("profile") or {}
    if not current:
        st.info("Set your company profile so RegWatch can assess which changes apply to you.")
    demo = json.loads((ROOT / "config" / "company_profile.json").read_text())
    default_text = json.dumps(current or demo, indent=2)
    text = st.text_area("Profile (JSON)", value=default_text, height=360)
    col1, col2 = st.columns([1, 4])
    if col1.button("Save profile", type="primary"):
        try:
            api().update_profile(json.loads(text))
            st.success("Profile saved.")
            st.rerun()
        except (RegWatchAPIError, json.JSONDecodeError) as exc:
            st.error(f"Could not save — {exc}")


# ── dashboard ────────────────────────────────────────────────────────────────

_PRIORITY_LABEL = {1: "Critical", 2: "High", 3: "Medium", 4: "Low", 5: "Low"}


def render_dashboard() -> None:
    top = st.container()
    if st.button("Run compliance pipeline", type="primary"):
        with st.spinner("Running version-aware pipeline…"):
            try:
                result = api().run_pipeline()
                st.success(
                    f"Run complete — {result['changes_detected']} changes, "
                    f"{result['tasks_generated']} tasks."
                )
            except RegWatchAPIError as exc:
                st.error(f"Pipeline failed — {exc.detail}")

    try:
        tasks = api().list_tasks()
    except RegWatchAPIError as exc:
        st.error(f"Could not load tasks — {exc.detail}")
        return

    pending = [t for t in tasks if t["status"] == "pending"]
    with top:
        c1, c2, c3 = st.columns(3)
        c1.metric("Open tasks", len(pending))
        c2.metric("Total tasks", len(tasks))
        c3.metric("Critical/High", sum(1 for t in tasks if t["priority"] <= 2))

    if not tasks:
        st.info("No compliance tasks yet. Run the pipeline to generate them.")
        return

    for t in tasks:
        st.markdown(
            f"<div class='rw-card'><div class='rw-pri'>"
            f"{_PRIORITY_LABEL.get(t['priority'], 'Low').upper()} · {t['status'].upper()}</div>"
            f"<div class='rw-title'>{t['title']}</div>"
            f"<div class='rw-meta'>{(t.get('description') or '')[:240]}</div>"
            f"<div class='rw-meta'>Citation: {t.get('citation','')}</div></div>",
            unsafe_allow_html=True,
        )
        a, b, _ = st.columns([1, 1, 6])
        if t["status"] == "pending" and a.button("Acknowledge", key=f"ack_{t['task_id']}"):
            api().acknowledge_task(t["task_id"]); st.rerun()
        if t["status"] != "completed" and b.button("Complete", key=f"done_{t['task_id']}"):
            api().complete_task(t["task_id"]); st.rerun()


def render_ask() -> None:
    st.subheader("Ask RegWatch")
    q = st.text_input("Ask about a regulation or what changed", placeholder="What changed in the namkeen filing requirements?")
    if q:
        with st.spinner("Retrieving…"):
            try:
                ans = api().query(q)
            except RegWatchAPIError as exc:
                st.error(f"Query failed — {exc.detail}")
                return
        st.markdown(ans.get("answer", ""))
        cites = [c for c in ans.get("citations", []) if c]
        if cites:
            st.caption("Sources: " + ", ".join(dict.fromkeys(cites)))


def render_runs() -> None:
    st.subheader("Pipeline runs")
    try:
        runs = api().list_runs()
    except RegWatchAPIError as exc:
        st.error(f"Could not load runs — {exc.detail}")
        return
    if not runs:
        st.info("No runs yet.")
        return
    st.dataframe(runs, use_container_width=True)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    if not st.session_state.get("token"):
        render_auth()
        return

    try:
        tenant = api().get_tenant()
    except RegWatchAPIError:
        st.session_state.token = None
        st.rerun()
        return

    with st.sidebar:
        st.markdown("### RegWatch")
        st.caption(st.session_state.get("email", ""))
        try:
            st.caption(f"API: {api().health().get('status', '?')}")
        except Exception:
            st.caption("API: unreachable")
        if st.button("Sign out"):
            st.session_state.clear()
            st.rerun()

    st.title("Compliance Operations")
    dash, ask, profile, runs = st.tabs(["Dashboard", "Ask", "Profile", "Runs"])
    with dash:
        render_dashboard()
    with ask:
        render_ask()
    with profile:
        render_profile(tenant)
    with runs:
        render_runs()


if __name__ == "__main__":
    main()
