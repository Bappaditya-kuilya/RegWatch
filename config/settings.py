from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
import streamlit as st

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def get_secret(name: str, default: str | None = None) -> str | None:
    if name in os.environ:
        return os.environ[name]
    try:
        value = st.secrets.get(name)
        if value is not None:
            return str(value)
    except Exception:
        pass
    return default


DATA_DIR = Path(get_secret("DATA_DIR", str(BASE_DIR / "data")))
LOG_LEVEL = get_secret("LOG_LEVEL", "INFO") or "INFO"
SCHEDULE_INTERVAL_HOURS = int(get_secret("SCHEDULE_INTERVAL_HOURS", "24") or "24")
