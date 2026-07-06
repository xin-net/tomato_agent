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
    vision_observation: dict[str, Any] | None = None
    multimodal_observation: dict[str, Any] | None = None
    weather_observation: dict[str, Any] | None = None
    date_observation: dict[str, Any] | None = None
    active_followup: dict[str, Any] | None = None
    history_summary: list[dict[str, Any]] = Field(default_factory=list)
    available_actions: list[AgentAction]


class AgentDecision(BaseModel):
    next_action: AgentAction
    reason: str
    confidence: str = "medium"
    requested_state: CaseStatus | None = None
    questions: list[str] = Field(default_factory=list)
    decision_source: str = "rule"
    observations_used: list[str] = Field(default_factory=list)
    tool_plan: list[str] = Field(default_factory=list)
    user_intent: str = "initial_diagnosis"
    response_focus: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    fallback_reason: str | None = None
