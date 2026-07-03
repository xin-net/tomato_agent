from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
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


@app.get("/api/cases/{case_id}/report", response_class=PlainTextResponse)
def case_report(case_id: int, db: Session = Depends(get_db)) -> PlainTextResponse:
    case = CaseRepository(db).get_detail(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    report = _build_case_report(case)
    return PlainTextResponse(
        report,
        headers={
            "Content-Disposition": f'attachment; filename="tomato-case-{case.id}.md"',
        },
    )


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
    lines.extend(["", "## 图片证据", ""])
    if image_evidence:
        lines.extend([f"- 图片 {index + 1}：{url}" for index, url in enumerate(image_evidence)])
        lines.append("")
        lines.append("> MVP 阶段仅保存图片证据，尚未执行视觉诊断。")
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
