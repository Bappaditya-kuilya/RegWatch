"""Thin httpx client for the RegWatch API — used by the Streamlit frontend.

The frontend holds NO pipeline/state logic; it only calls these endpoints with the
tenant's bearer token. This is the seam that makes Streamlit just one client of the
backend (Next.js could replace it later without touching the API).
"""

from __future__ import annotations

import httpx


class RegWatchAPIError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


class RegWatchAPI:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ── internals ────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _request(self, method: str, path: str, **kwargs):
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            resp = client.request(method, path, headers=self._headers(), **kwargs)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise RegWatchAPIError(resp.status_code, str(detail))
        return resp.json()

    # ── auth ─────────────────────────────────────────────────────────────────

    def register(self, email: str, password: str, company_name: str) -> dict:
        return self._request("POST", "/auth/register", json={
            "email": email, "password": password, "company_name": company_name,
        })

    def login(self, email: str, password: str) -> str:
        data = self._request("POST", "/auth/login", json={"email": email, "password": password})
        self.token = data["access_token"]
        return self.token

    # ── tenant ───────────────────────────────────────────────────────────────

    def get_tenant(self) -> dict:
        return self._request("GET", "/tenant")

    def update_profile(self, profile: dict) -> dict:
        return self._request("PUT", "/tenant/profile", json=profile)

    # ── pipeline / tasks / query ──────────────────────────────────────────────

    def run_pipeline(self) -> dict:
        return self._request("POST", "/pipeline/run")

    def list_runs(self) -> list[dict]:
        return self._request("GET", "/pipeline/runs")

    def list_tasks(self, status: str | None = None) -> list[dict]:
        params = {"status": status} if status else None
        return self._request("GET", "/tasks", params=params)

    def acknowledge_task(self, task_id: str) -> dict:
        return self._request("PATCH", f"/tasks/{task_id}/acknowledge")

    def complete_task(self, task_id: str) -> dict:
        return self._request("PATCH", f"/tasks/{task_id}/complete")

    def query(self, text: str) -> dict:
        return self._request("POST", "/query", json={"query": text})

    def health(self) -> dict:
        return self._request("GET", "/health")
