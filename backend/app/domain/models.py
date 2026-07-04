from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base
from app.domain.enums import CaseStatus, FollowupStatus


def json_type():
    return JSON().with_variant(JSONB, "postgresql")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    auth_provider: Mapped[str] = mapped_column(String(30), default="password", index=True)
    provider_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(30), default="user", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), default="番茄异常病例")
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    crop: Mapped[str] = mapped_column(String(50), default="番茄")
    environment: Mapped[str | None] = mapped_column(String(50), nullable=True)
    growth_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    symptoms: Mapped[str] = mapped_column(Text, default="")
    affected_parts: Mapped[list] = mapped_column(MutableList.as_mutable(json_type()), default=list)
    severity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    recent_weather: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recent_fertilizer_use: Mapped[str | None] = mapped_column(String(50), nullable=True)
    recent_pesticide_use: Mapped[str | None] = mapped_column(String(50), nullable=True)
    days_to_harvest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suspected_problem: Mapped[str | None] = mapped_column(String(100), nullable=True)
    likelihood: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default=CaseStatus.NEW.value, index=True)
    structured_data: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), default=dict)
    current_plan: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), default=dict)
    followup_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    events: Mapped[list["CaseEvent"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="CaseEvent.created_at"
    )
    followups: Mapped[list["Followup"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )


class CaseEvent(Base):
    __tablename__ = "case_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    user_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_output: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), default=dict)
    structured_data: Mapped[dict] = mapped_column(MutableDict.as_mutable(json_type()), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case: Mapped[Case] = relationship(back_populates="events")


class Followup(Base):
    __tablename__ = "followups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    checklist: Mapped[list] = mapped_column(MutableList.as_mutable(json_type()), default=list)
    status: Mapped[str] = mapped_column(String(50), default=FollowupStatus.PENDING.value, index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case: Mapped[Case] = relationship(back_populates="followups")


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    followup_id: Mapped[int | None] = mapped_column(
        ForeignKey("followups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    channel: Mapped[str] = mapped_column(String(50), default="in_app", index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
