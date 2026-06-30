from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from app.core.database import Base, engine, get_db
from app.repositories.case_repository import CaseRepository
from app.schemas.cases import (
    CaseDetail,
    CaseListItem,
    CaseResponse,
    CloseCaseInput,
    CreateCaseInput,
    FollowupInput,
    ReplyInput,
)
from app.services.case_orchestrator import CaseOrchestrator

app = FastAPI(title="Tomato Case Agent", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/cases", response_model=CaseResponse)
def create_case(data: CreateCaseInput, db: Session = Depends(get_db)) -> CaseResponse:
    return CaseOrchestrator(db).create_case(data)


@app.post("/api/cases/{case_id}/reply", response_model=CaseResponse)
def reply_to_case(case_id: int, data: ReplyInput, db: Session = Depends(get_db)) -> CaseResponse:
    try:
        return CaseOrchestrator(db).reply_to_case(case_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/cases/{case_id}/followup", response_model=CaseResponse)
def submit_followup(
    case_id: int, data: FollowupInput, db: Session = Depends(get_db)
) -> CaseResponse:
    try:
        return CaseOrchestrator(db).submit_followup(case_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/cases/{case_id}/close", response_model=CaseResponse)
def close_case(case_id: int, data: CloseCaseInput, db: Session = Depends(get_db)) -> CaseResponse:
    try:
        return CaseOrchestrator(db).close_case(case_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/cases", response_model=list[CaseListItem])
def list_cases(status: str | None = None, db: Session = Depends(get_db)) -> list[CaseListItem]:
    return CaseRepository(db).list(status=status)


@app.get("/api/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: int, db: Session = Depends(get_db)) -> CaseDetail:
    case = CaseRepository(db).get_detail(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case
