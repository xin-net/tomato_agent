from pydantic import BaseModel, Field


class KnowledgeEntry(BaseModel):
    problem_name: str
    category: str
    typical_symptoms: list[str] = Field(default_factory=list)
    affected_parts: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    confusions: list[str] = Field(default_factory=list)
    evidence_keywords: list[str] = Field(default_factory=list)
    non_chemical_actions: list[str] = Field(default_factory=list)
    observation_points: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
