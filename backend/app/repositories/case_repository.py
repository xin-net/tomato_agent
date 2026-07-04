from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.domain.enums import CaseStatus
from app.domain.models import Case
from app.schemas.cases import CreateCaseInput


class CaseRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: CreateCaseInput, title: str) -> Case:
        case = Case(
            title=title,
            user_id=data.user_id,
            crop=data.crop,
            environment=data.environment,
            growth_stage=data.growth_stage,
            symptoms=data.symptoms,
            affected_parts=data.affected_parts,
            severity=data.severity,
            recent_weather=data.recent_weather,
            recent_fertilizer_use=data.recent_fertilizer_use,
            recent_pesticide_use=data.recent_pesticide_use,
            days_to_harvest=data.days_to_harvest,
        )
        self.db.add(case)
        self.db.flush()
        return case

    def get(self, case_id: int, user_id: str | None = None, include_all: bool = False) -> Case | None:
        stmt = select(Case).where(Case.id == case_id)
        if user_id is not None and not include_all:
            stmt = stmt.where(Case.user_id == user_id)
        return self.db.scalar(stmt)

    def get_detail(
        self, case_id: int, user_id: str | None = None, include_all: bool = False
    ) -> Case | None:
        stmt = (
            select(Case)
            .options(selectinload(Case.events), selectinload(Case.followups))
            .where(Case.id == case_id)
        )
        if user_id is not None and not include_all:
            stmt = stmt.where(Case.user_id == user_id)
        return self.db.scalar(stmt)

    def list(
        self, status: str | None = None, user_id: str | None = None, include_all: bool = False
    ) -> list[Case]:
        stmt = select(Case).order_by(Case.updated_at.desc())
        if status:
            stmt = stmt.where(Case.status == status)
        if user_id is not None and not include_all:
            stmt = stmt.where(Case.user_id == user_id)
        return list(self.db.scalars(stmt))

    def latest_active_for_user(self, user_id: str) -> Case | None:
        stmt = (
            select(Case)
            .where(
                Case.user_id == user_id,
                Case.status.notin_([CaseStatus.CLOSED.value, CaseStatus.ESCALATED.value]),
            )
            .order_by(Case.updated_at.desc(), Case.id.desc())
        )
        return self.db.scalar(stmt)
