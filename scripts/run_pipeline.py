from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sqlite3

from core.models import CompanyProfile
from graph.pipeline import build_pipeline

with open("config/company_profile.json", encoding="utf-8") as f:
    profile = CompanyProfile(**json.load(f))

pipeline = build_pipeline()
conn = sqlite3.connect("data/registry.db")
seeded_doc_ids = [row[0] for row in conn.execute("select doc_id from documents").fetchall()]
result = pipeline.invoke(
    {
        "trigger": "seeded",
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
        "run_mode": "CLI Seeded",
    },
    config={"configurable": {"thread_id": "manual-run"}},
)
print(result)
