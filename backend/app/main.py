from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.core.database import Base, engine, get_db
from app.repositories.case_repository import CaseRepository
from app.schemas.cases import (
    CaseDetail,
    CaseEventRead,
    CaseListItem,
    CaseResponse,
    CloseCaseInput,
    CreateCaseInput,
    FollowupInput,
    ReplyInput,
)
from app.schemas.conversation import ConversationMessageInput, ConversationMessageResponse
from app.services.case_orchestrator import CaseOrchestrator
from app.services.conversation_service import ConversationService

app = FastAPI(title="Tomato Case Agent", version="0.1.0")
STATIC_DIR = Path(__file__).resolve().parent / "static"
FRONTEND_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if (FRONTEND_DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST_DIR / "assets"), name="frontend-assets")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    frontend_index = FRONTEND_DIST_DIR / "index.html"
    if frontend_index.exists():
        return FileResponse(frontend_index)
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/cases", response_model=CaseResponse)
def create_case(data: CreateCaseInput, db: Session = Depends(get_db)) -> CaseResponse:
    return CaseOrchestrator(db).create_case(data)


@app.post("/api/conversation/messages", response_model=ConversationMessageResponse)
def send_conversation_message(
    data: ConversationMessageInput, db: Session = Depends(get_db)
) -> ConversationMessageResponse:
    return ConversationService(db).handle_message(data)


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


@app.get("/api/cases/{case_id}/events", response_model=list[CaseEventRead])
def list_case_events(case_id: int, db: Session = Depends(get_db)) -> list[CaseEventRead]:
    case = CaseRepository(db).get_detail(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return list(case.events)
