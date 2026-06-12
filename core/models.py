from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ChangeSeverity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class ChangeType(str, Enum):
    RATE_CHANGE = "rate_change"
    DEADLINE_CHANGE = "deadline_change"
    NEW_REQUIREMENT = "new_requirement"
    REMOVED_RULE = "removed_rule"
    PROCEDURAL_CHANGE = "procedural_change"
    PENALTY_CHANGE = "penalty_change"
    DEFINITION_CHANGE = "definition_change"


class SemanticChange(BaseModel):
    change_id: str
    doc_id: str
    old_version: str
    new_version: str
    change_type: ChangeType
    severity: ChangeSeverity
    old_text_summary: str
    new_text_summary: str
    affected_clauses: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    raw_diff_context: str


class ImpactAssessment(BaseModel):
    change_id: str
    is_applicable: bool
    applicability_reason: str
    affected_operations: list[str]
    affected_product_categories: list[str]
    risk_level: ChangeSeverity
    requires_action: bool


class ComplianceTask(BaseModel):
    task_id: str
    title: str
    description: str
    source_change_id: str
    deadline: Optional[datetime]
    deadline_source: str
    penalty_if_missed: Optional[str]
    priority: int = Field(ge=1, le=5)
    status: Literal["pending", "acknowledged", "completed"] = "pending"
    citation: str
    action_url: Optional[str] = None


class DiffResponse(BaseModel):
    """Exact shape the diff LLM must return (the full SemanticChange is composed in code)."""

    change_type: ChangeType
    severity: ChangeSeverity
    old_text_summary: str
    new_text_summary: str
    affected_clauses: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    key_phrase_changed: str = ""


class ImpactResponse(BaseModel):
    """Exact shape the impact-mapper LLM must return."""

    is_applicable: bool
    applicability_reason: str
    affected_operations: list[str] = Field(default_factory=list)
    affected_product_categories: list[str] = Field(default_factory=list)
    risk_level: ChangeSeverity
    requires_action: bool


class ActionResponse(BaseModel):
    """Exact shape the action-planner LLM must return (deadline parsed in code)."""

    title: str
    description: str
    deadline: Optional[str] = None
    deadline_source: str = ""
    penalty_if_missed: Optional[str] = None
    priority: int = Field(ge=1, le=5)


class CompanyProfile(BaseModel):
    company_name: str
    business_type: str
    udyam_id: Optional[str] = None
    gstin: Optional[str] = None
    fssai_license: Optional[str] = None
    product_categories: list[str]
    hsn_codes: list[str]
    applicable_acts: list[str]
    employee_count_range: str
    state: str
    annual_turnover_range: str
    specific_watch_terms: list[str] = Field(default_factory=list)
