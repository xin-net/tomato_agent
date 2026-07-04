from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import Base, engine, get_db
from app.core.security import create_access_token, verify_password
from app.domain.models import User
from app.repositories.case_repository import CaseRepository
from app.repositories.reminder_repository import ReminderRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse, UserCreate, UserLogin, UserRead
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
from app.schemas.reminders import ReminderCreate, ReminderRead, ReminderUpdate
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


@app.get("/api/system/status")
def system_status() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "app": "Tomato Case Agent",
        "version": app.version,
        "frontend_dist_available": (FRONTEND_DIST_DIR / "index.html").exists(),
    }


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    frontend_index = FRONTEND_DIST_DIR / "index.html"
    if frontend_index.exists():
        return FileResponse(frontend_index)
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/auth/register", response_model=TokenResponse)
def register(data: UserCreate, db: Session = Depends(get_db)) -> TokenResponse:
    users = UserRepository(db)
    if users.get_by_username(data.username):
        raise HTTPException(status_code=409, detail="Username already exists")
    user = users.create(data)
    db.commit()
    token = create_access_token(str(user.id), {"role": user.role})
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))


@app.post("/api/auth/login", response_model=TokenResponse)
def login(data: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    user = UserRepository(db).get_by_username(data.username)
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(str(user.id), {"role": user.role})
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))


@app.get("/api/auth/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)


@app.post("/api/cases", response_model=CaseResponse)
def create_case(
    data: CreateCaseInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseResponse:
    data.user_id = str(current_user.id)
    return CaseOrchestrator(db).create_case(data)


@app.post("/api/conversation/messages", response_model=ConversationMessageResponse)
def send_conversation_message(
    data: ConversationMessageInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationMessageResponse:
    if data.case_id is not None:
        _require_case_access(data.case_id, db, current_user)
    data.user_id = str(current_user.id)
    return ConversationService(db).handle_message(data)


def _require_case_access(case_id: int, db: Session, current_user: User | None):
    case = CaseRepository(db).get(
        case_id,
        user_id=str(current_user.id) if current_user else None,
        include_all=current_user.role == "admin" if current_user else False,
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.post("/api/cases/{case_id}/reply", response_model=CaseResponse)
def reply_to_case(
    case_id: int,
    data: ReplyInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseResponse:
    _require_case_access(case_id, db, current_user)
    try:
        return CaseOrchestrator(db).reply_to_case(case_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/cases/{case_id}/followup", response_model=CaseResponse)
def submit_followup(
    case_id: int,
    data: FollowupInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseResponse:
    _require_case_access(case_id, db, current_user)
    try:
        return CaseOrchestrator(db).submit_followup(case_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/cases/{case_id}/close", response_model=CaseResponse)
def close_case(
    case_id: int,
    data: CloseCaseInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseResponse:
    _require_case_access(case_id, db, current_user)
    try:
        return CaseOrchestrator(db).close_case(case_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/cases", response_model=list[CaseListItem])
def list_cases(
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CaseListItem]:
    return CaseRepository(db).list(
        status=status,
        user_id=str(current_user.id),
        include_all=current_user.role == "admin",
    )


@app.get("/api/cases/{case_id}", response_model=CaseDetail)
def get_case(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CaseDetail:
    case = CaseRepository(db).get_detail(
        case_id,
        user_id=str(current_user.id),
        include_all=current_user.role == "admin",
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.get("/api/cases/{case_id}/events", response_model=list[CaseEventRead])
def list_case_events(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CaseEventRead]:
    case = CaseRepository(db).get_detail(
        case_id,
        user_id=str(current_user.id),
        include_all=current_user.role == "admin",
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return list(case.events)


@app.get("/api/cases/{case_id}/report", response_class=PlainTextResponse)
def case_report(
    case_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PlainTextResponse:
    case = CaseRepository(db).get_detail(
        case_id,
        user_id=str(current_user.id),
        include_all=current_user.role == "admin",
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    report = _build_case_report(case)
    return PlainTextResponse(
        report,
        headers={
            "Content-Disposition": f'attachment; filename="tomato-case-{case.id}.md"',
        },
    )


@app.get("/api/reminders", response_model=list[ReminderRead])
def list_reminders(
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ReminderRead]:
    cases = CaseRepository(db).list(
        user_id=str(current_user.id),
        include_all=current_user.role == "admin",
    )
    reminders = ReminderRepository(db).list(
        user_case_ids=[case.id for case in cases] if current_user.role != "admin" else None,
        status=status,
    )
    return [ReminderRead.model_validate(reminder) for reminder in reminders]


@app.get("/api/reminders/due", response_model=list[ReminderRead])
def due_reminders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ReminderRead]:
    cases = CaseRepository(db).list(
        user_id=str(current_user.id),
        include_all=current_user.role == "admin",
    )
    reminders = ReminderRepository(db).due(
        user_case_ids=[case.id for case in cases] if current_user.role != "admin" else None,
    )
    return [ReminderRead.model_validate(reminder) for reminder in reminders]


@app.post("/api/reminders", response_model=ReminderRead)
def create_reminder(
    data: ReminderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReminderRead:
    _require_case_access(data.case_id, db, current_user)
    reminder = ReminderRepository(db).create(data)
    db.commit()
    return ReminderRead.model_validate(reminder)


@app.patch("/api/reminders/{reminder_id}", response_model=ReminderRead)
def update_reminder(
    reminder_id: int,
    data: ReminderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReminderRead:
    reminders = ReminderRepository(db)
    reminder = reminders.get(reminder_id)
    if reminder is None:
        raise HTTPException(status_code=404, detail="Reminder not found")
    _require_case_access(reminder.case_id, db, current_user)
    updated = reminders.update(reminder, data)
    db.commit()
    return ReminderRead.model_validate(updated)


def _build_case_report(case) -> str:
    lines = [
        f"# Tomato Case #{case.id}",
        "",
        "## 基本信息",
        "",
        f"- 标题：{case.title}",
        f"- 作物：{case.crop}",
        f"- 状态：{case.status}",
        f"- 疑似问题：{case.suspected_problem or '-'}",
        f"- 可信度：{case.likelihood or '-'}",
        f"- 生长阶段：{case.growth_stage or '-'}",
        f"- 种植环境：{case.environment or '-'}",
        f"- 近期天气：{case.recent_weather or '-'}",
        f"- 距离采收：{case.days_to_harvest if case.days_to_harvest is not None else '-'} 天",
        f"- 发生部位：{'、'.join(map(str, case.affected_parts or [])) or '-'}",
        "",
        "## 用户症状描述",
        "",
        case.symptoms or "-",
        "",
        "## 当前处置方案",
        "",
    ]

    plan = case.current_plan or {}
    if plan:
        lines.extend(
            [
                f"摘要：{plan.get('summary', '-')}",
                "",
                "立即动作：",
                *[f"- {item}" for item in plan.get("immediate_actions", [])],
                "",
                "观察重点：",
                *[f"- {item}" for item in plan.get("observation_points", [])],
                "",
                "升级条件：",
                *[f"- {item}" for item in plan.get("escalation_conditions", [])],
                "",
                "安全提醒：",
                *[f"- {item}" for item in plan.get("safety_warnings", [])],
            ]
        )
    else:
        lines.append("-")

    image_evidence = (case.structured_data or {}).get("image_evidence", [])
    vision_observation = (case.structured_data or {}).get("vision_observation")
    image_analysis_status = (case.structured_data or {}).get("image_analysis_status", "-")
    lines.extend(["", "## 图片证据", ""])
    if image_evidence:
        lines.extend([f"- 图片 {index + 1}：{url}" for index, url in enumerate(image_evidence)])
        lines.append("")
        lines.append(f"> 图片分析状态：{image_analysis_status}")
        if vision_observation:
            uncertainties = vision_observation.get("uncertainties", [])
            if uncertainties:
                lines.extend([f"> - {item}" for item in uncertainties])
    else:
        lines.append("-")

    lines.extend(["", "## 复查记录", ""])
    if case.followups:
        for followup in case.followups:
            lines.extend(
                [
                    f"- 复查 #{followup.id}：{followup.due_date} / {followup.status}",
                    f"  - 结果：{followup.result or '-'}",
                    f"  - 用户描述：{followup.user_description or '-'}",
                ]
            )
    else:
        lines.append("-")

    lines.extend(["", "## 事件时间线", ""])
    if case.events:
        for event in case.events:
            lines.append(f"- {event.created_at} `{event.event_type}`")
            if event.user_input:
                lines.append(f"  - 用户输入：{event.user_input}")
            if event.system_output:
                lines.append(f"  - 系统输出：{event.system_output}")
    else:
        lines.append("-")

    lines.append("")
    return "\n".join(lines)
