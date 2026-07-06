from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import FollowupStatus
from app.domain.models import Followup


class FollowupRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, case_id: int, due_date: date, checklist: list[str]) -> Followup:
        followup = Followup(case_id=case_id, due_date=due_date, checklist=checklist)
        self.db.add(followup)
        self.db.flush()
        return followup

    def get(self, followup_id: int) -> Followup | None:
        return self.db.get(Followup, followup_id)

    def active_for_case(self, case_id: int) -> Followup | None:
        stmt = (
            select(Followup)
            .where(Followup.case_id == case_id, Followup.status == FollowupStatus.PENDING.value)
            .order_by(Followup.due_date.asc())
        )
        return self.db.scalar(stmt)

    def submit(self, followup: Followup, description: str, result: str) -> Followup:
        followup.status = FollowupStatus.SUBMITTED.value
        followup.submitted_at = datetime.now(timezone.utc)
        followup.user_description = description
        followup.result = result
        self.db.flush()
        return followup

    def reschedule(self, followup: Followup, due_date: date, checklist: list[str]) -> Followup:
        followup.due_date = due_date
        followup.checklist = checklist
        self.db.flush()
        return followup
