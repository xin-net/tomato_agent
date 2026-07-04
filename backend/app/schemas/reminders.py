from datetime import datetime

from pydantic import BaseModel


class ReminderCreate(BaseModel):
    case_id: int
    followup_id: int | None = None
    due_at: datetime
    channel: str = "in_app"
    reason: str | None = None


class ReminderRead(BaseModel):
    id: int
    case_id: int
    followup_id: int | None = None
    due_at: datetime
    channel: str
    status: str
    reason: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReminderUpdate(BaseModel):
    due_at: datetime | None = None
    status: str | None = None
    reason: str | None = None
