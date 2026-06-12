"""FastAPI service configuration.

Reads from environment / Streamlit secrets via the shared ``get_secret`` helper so the
backend, CLI, and Streamlit frontend all resolve secrets the same way. No new settings
dependency — keeps the Render image light.
"""

from __future__ import annotations

from config.settings import get_secret

SERVICE_NAME = "regwatch-api"
VERSION = "2.0.0"


class ApiConfig:
    def __init__(self) -> None:
        self.allowed_origins = self._origins()
        self.jwt_secret = get_secret("JWT_SECRET")
        self.supabase_url = get_secret("SUPABASE_URL")
        self.supabase_anon_key = get_secret("SUPABASE_ANON_KEY")
        self.supabase_service_key = get_secret("SUPABASE_SERVICE_ROLE_KEY")

    @staticmethod
    def _origins() -> list[str]:
        raw = get_secret("ALLOWED_ORIGINS", "http://localhost:8501") or ""
        return [o.strip() for o in raw.split(",") if o.strip()]


config = ApiConfig()
