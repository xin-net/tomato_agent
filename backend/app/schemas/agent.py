from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import AgentAction, CaseStatus


class StructuredSymptoms(BaseModel):
    crop: str = "番茄"
    affected_parts: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    possible_categories: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    severity: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class AgentDecisionContext(BaseModel):
    case_status: CaseStatus
    latest_user_message: str
    structured_symptoms: StructuredSymptoms
    active_followup: dict[str, Any] | None = None
    history_summary: list[dict[str, Any]] = Field(default_factory=list)
    available_actions: list[AgentAction]


class AgentDecision(BaseModel):
    next_action: AgentAction
    reason: str
    confidence: str = "medium"
    requested_state: CaseStatus | None = None
    questions: list[str] = Field(default_factory=list)
