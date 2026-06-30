from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import EventType
from app.domain.models import CaseEvent


class EventRepository:
    def __init__(self, db: Session):
        self.db = db

    def append(
        self,
        case_id: int,
        event_type: EventType,
        user_input: str | None = None,
        system_output: dict | None = None,
        structured_data: dict | None = None,
    ) -> CaseEvent:
        event = CaseEvent(
            case_id=case_id,
            event_type=event_type.value,
            user_input=user_input,
            system_output=system_output or {},
            structured_data=structured_data or {},
        )
        self.db.add(event)
        self.db.flush()
        return event

    def list_for_case(self, case_id: int) -> list[CaseEvent]:
        stmt = select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.created_at)
        return list(self.db.scalars(stmt))
