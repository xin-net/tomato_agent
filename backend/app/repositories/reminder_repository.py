from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import Reminder
from app.schemas.reminders import ReminderCreate, ReminderUpdate


class ReminderRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: ReminderCreate) -> Reminder:
        reminder = Reminder(**data.model_dump())
        self.db.add(reminder)
        self.db.flush()
        return reminder

    def get(self, reminder_id: int) -> Reminder | None:
        return self.db.get(Reminder, reminder_id)

    def pending_for_followup(self, followup_id: int) -> Reminder | None:
        stmt = (
            select(Reminder)
            .where(Reminder.followup_id == followup_id, Reminder.status == "pending")
            .order_by(Reminder.due_at.asc())
        )
        return self.db.scalar(stmt)

    def list(
        self,
        user_case_ids: list[int] | None = None,
        status: str | None = None,
        due_before: datetime | None = None,
    ) -> list[Reminder]:
        stmt = select(Reminder).order_by(Reminder.due_at.asc(), Reminder.id.asc())
        if user_case_ids is not None:
            if not user_case_ids:
                return []
            stmt = stmt.where(Reminder.case_id.in_(user_case_ids))
        if status:
            stmt = stmt.where(Reminder.status == status)
        if due_before:
            stmt = stmt.where(Reminder.due_at <= due_before)
        return list(self.db.scalars(stmt))

    def due(self, user_case_ids: list[int] | None = None) -> list[Reminder]:
        return self.list(
            user_case_ids=user_case_ids,
            status="pending",
            due_before=datetime.now(timezone.utc),
        )

    def update(self, reminder: Reminder, data: ReminderUpdate) -> Reminder:
        updates = data.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(reminder, key, value)
        self.db.flush()
        return reminder

    def cancel_for_followup(self, followup_id: int) -> None:
        stmt = select(Reminder).where(
            Reminder.followup_id == followup_id,
            Reminder.status == "pending",
        )
        for reminder in self.db.scalars(stmt):
            reminder.status = "cancelled"
        self.db.flush()

    def reschedule_for_followup(
        self,
        followup_id: int,
        due_at: datetime,
        reason: str,
        channel: str | None = None,
    ) -> None:
        stmt = select(Reminder).where(
            Reminder.followup_id == followup_id,
            Reminder.status == "pending",
        )
        for reminder in self.db.scalars(stmt):
            reminder.due_at = due_at
            reminder.reason = reason
            if channel:
                reminder.channel = channel
        self.db.flush()
