from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import AgentAction, CaseStatus, FollowupTrend


class CreateCaseInput(BaseModel):
    user_id: str | None = None
    crop: str = "番茄"
    environment: str | None = None
    growth_stage: str | None = None
    symptoms: str
    affected_parts: list[str] = Field(default_factory=list)
    severity: str | None = None
    recent_weather: str | None = None
    recent_fertilizer_use: str | None = None
    recent_pesticide_use: str | None = None
    days_to_harvest: int | None = None
    image_urls: list[str] = Field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    location_label: str | None = None
    location_source: str | None = None
    location_error: str | None = None


class ReplyInput(BaseModel):
    message: str
    image_urls: list[str] = Field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    location_label: str | None = None
    location_source: str | None = None
    location_error: str | None = None


class FollowupInput(BaseModel):
    description: str
    actions_done: list[str] = Field(default_factory=list)
    has_new_spots: bool | None = None
    spots_expanded: bool | None = None
    spread_to_new_parts: bool | None = None
    fruit_affected: bool | None = None


class CloseCaseInput(BaseModel):
    summary: str | None = None


class CaseEventRead(BaseModel):
    id: int
    event_type: str
    user_input: str | None = None
    system_output: dict[str, Any] = Field(default_factory=dict)
    structured_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class FollowupRead(BaseModel):
    id: int
    due_date: date
    checklist: list[Any] = Field(default_factory=list)
    status: str
    submitted_at: datetime | None = None
    user_description: str | None = None
    result: str | None = None

    model_config = {"from_attributes": True}


class AgentDecisionRead(BaseModel):
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
    information_sufficient: bool | None = None
    problem_category: str | None = None
    likely_causes: list[str] = Field(default_factory=list)
    diagnosis_evidence: list[str] = Field(default_factory=list)
    confidence_label: str | None = None
    severity_label: str | None = None
    immediate_actions: list[str] = Field(default_factory=list)
    observation_points: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    followup_after_days: int | None = None
    followup_trend: FollowupTrend | None = None
    followup_evidence: list[str] = Field(default_factory=list)
    chemical_safety_note: str | None = None
    harvest_safety_note: str | None = None
    plain_summary: str | None = None


class SafetyResultRead(BaseModel):
    chemical_detail_allowed: bool
    risk_level: str
    warnings: list[str] = Field(default_factory=list)
    must_escalate: bool = False


class DiagnosisRead(BaseModel):
    suspected_problem: str | None = None
    likelihood: str | None = None
    evidence: list[str] = Field(default_factory=list)
    confusions: list[str] = Field(default_factory=list)


class PlanRead(BaseModel):
    summary: str
    immediate_actions: list[str] = Field(default_factory=list)
    observation_points: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    safety_warnings: list[str] = Field(default_factory=list)
    followup_after_days: int | None = None


class ClosedLoopAdvice(BaseModel):
    information_sufficient: bool
    problem_category: str | None = None
    severity: str
    action_mode: str
    chemical_advice: str
    harvest_safety: str
    plain_summary: str
    immediate_actions: list[str] = Field(default_factory=list)
    observation_points: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    followup_timing: str | None = None
    followup_if_better: list[str] = Field(default_factory=list)
    followup_if_worse: list[str] = Field(default_factory=list)
    process_record: list[str] = Field(default_factory=list)
    environment_confirmation: str | None = None


class CaseResponse(BaseModel):
    case_id: int
    status: CaseStatus
    response_type: str
    message: str
    decision: AgentDecisionRead | None = None
    diagnosis: DiagnosisRead | None = None
    plan: PlanRead | None = None
    safety: SafetyResultRead | None = None
    followup: FollowupRead | None = None
    trend: FollowupTrend | None = None
    advice: ClosedLoopAdvice | None = None


class CaseListItem(BaseModel):
    id: int
    title: str
    crop: str
    suspected_problem: str | None = None
    status: str
    followup_date: date | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CaseDetail(BaseModel):
    id: int
    title: str
    user_id: str | None = None
    crop: str
    environment: str | None = None
    growth_stage: str | None = None
    symptoms: str
    affected_parts: list[Any] = Field(default_factory=list)
    severity: str | None = None
    recent_weather: str | None = None
    recent_fertilizer_use: str | None = None
    recent_pesticide_use: str | None = None
    days_to_harvest: int | None = None
    suspected_problem: str | None = None
    likelihood: str | None = None
    status: str
    structured_data: dict[str, Any] = Field(default_factory=dict)
    current_plan: dict[str, Any] = Field(default_factory=dict)
    followup_date: date | None = None
    created_at: datetime
    updated_at: datetime
    events: list[CaseEventRead] = Field(default_factory=list)
    followups: list[FollowupRead] = Field(default_factory=list)

    model_config = {"from_attributes": True}
