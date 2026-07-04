from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.agents.decision_engine import AgentDecisionEngine
from app.domain.enums import AgentAction, CaseStatus, EventType, FollowupTrend
from app.domain.safety import SafetyChecker, SafetyContext
from app.domain.state_machine import StateMachine
from app.repositories.case_repository import CaseRepository
from app.repositories.event_repository import EventRepository
from app.repositories.followup_repository import FollowupRepository
from app.repositories.reminder_repository import ReminderRepository
from app.schemas.agent import AgentDecisionContext
from app.schemas.cases import (
    AgentDecisionRead,
    CaseResponse,
    CloseCaseInput,
    CreateCaseInput,
    DiagnosisRead,
    FollowupInput,
    FollowupRead,
    PlanRead,
    ReplyInput,
    SafetyResultRead,
)
from app.schemas.reminders import ReminderCreate
from app.tools.diagnosis_tool import DiagnosisTool, PlanTool
from app.tools.followup_compare_tool import FollowupCompareTool
from app.tools.knowledge_search_tool import KnowledgeSearchTool
from app.tools.symptom_extraction_tool import SymptomExtractionTool
from app.tools.vision_tool import VisionTool
from app.tools.weather_tool import WeatherTool


class CaseOrchestrator:
    def __init__(self, db: Session):
        self.db = db
        self.cases = CaseRepository(db)
        self.events = EventRepository(db)
        self.followups = FollowupRepository(db)
        self.reminders = ReminderRepository(db)
        self.extractor = SymptomExtractionTool()
        self.decision_engine = AgentDecisionEngine()
        self.knowledge = KnowledgeSearchTool()
        self.diagnosis_tool = DiagnosisTool()
        self.plan_tool = PlanTool()
        self.followup_compare = FollowupCompareTool()
        self.vision_tool = VisionTool()
        self.weather_tool = WeatherTool()
        self.state_machine = StateMachine()
        self.safety = SafetyChecker()

    def create_case(self, data: CreateCaseInput) -> CaseResponse:
        title = self._make_title(data.symptoms)
        case = self.cases.create(data, title=title)
        self.events.append(case.id, EventType.CASE_CREATED, user_input=data.symptoms)
        self._append_user_message(case.id, data.symptoms, data.image_urls)
        self._append_image_evidence(case, data.image_urls)
        self._observe_weather(case, data.symptoms)

        response = self._handle_message(case, data.symptoms)
        self._append_agent_response(case.id, response)
        self.db.commit()
        return response

    def reply_to_case(self, case_id: int, data: ReplyInput) -> CaseResponse:
        case = self._require_case(case_id)
        case.symptoms = f"{case.symptoms}\n{data.message}".strip()
        self._append_user_message(case.id, data.message, data.image_urls)
        self._append_image_evidence(case, data.image_urls)
        self._observe_weather(case, data.message)
        response = self._handle_message(case, data.message)
        self._append_agent_response(case.id, response)
        self.db.commit()
        return response

    def submit_followup(
        self, case_id: int, data: FollowupInput, record_response: bool = True
    ) -> CaseResponse:
        case = self._require_case(case_id)
        active = self.followups.active_for_case(case.id)
        self.events.append(case.id, EventType.FOLLOWUP_SUBMITTED, user_input=data.description)

        trend, evidence = self.followup_compare.compare(data)
        requested_state = self._state_for_trend(trend)
        if (
            CaseStatus(case.status) == CaseStatus.FOLLOWUP_PENDING
            and requested_state
            in {
                CaseStatus.IMPROVING,
                CaseStatus.WORSENING,
                CaseStatus.NEED_MORE_INFO,
                CaseStatus.CLOSED,
            }
        ):
            self.state_machine.apply(case, CaseStatus.FOLLOWUP_REVIEW, "进入复查判断")
        transition = self.state_machine.apply(case, requested_state, "复查趋势判断")
        if not transition.allowed:
            requested_state = CaseStatus.ESCALATED
            self.state_machine.apply(case, requested_state, transition.reason)

        if active:
            self.followups.submit(active, data.description, trend.value)
            self.reminders.cancel_for_followup(active.id)
            self.events.append(
                case.id,
                EventType.REMINDER_CANCELLED,
                system_output={"followup_id": active.id, "reason": "用户已提交复查"},
            )

        system_output = {"trend": trend.value, "evidence": evidence}
        self.events.append(case.id, EventType.FOLLOWUP_COMPARED, system_output=system_output)
        self.events.append(
            case.id,
            EventType.STATE_CHANGED,
            system_output={"status": case.status, "reason": "复查趋势判断"},
        )

        message = self._followup_message(trend)
        response = CaseResponse(
            case_id=case.id,
            status=CaseStatus(case.status),
            response_type="followup_result",
            message=message,
            trend=trend,
            followup=FollowupRead.model_validate(active) if active else None,
        )
        if record_response:
            self._append_agent_response(case.id, response)
        self.db.commit()
        return response

    def close_case(self, case_id: int, data: CloseCaseInput) -> CaseResponse:
        case = self._require_case(case_id)
        transition = self.state_machine.apply(case, CaseStatus.CLOSED, "用户确认结案")
        if not transition.allowed:
            return CaseResponse(
                case_id=case.id,
                status=CaseStatus(case.status),
                response_type="state_rejected",
                message=transition.reason,
            )

        summary = data.summary or "用户确认当前病例可以结案。"
        self.events.append(
            case.id,
            EventType.CASE_CLOSED,
            system_output={"summary": summary},
        )
        response = CaseResponse(
            case_id=case.id,
            status=CaseStatus(case.status),
            response_type="closed",
            message=f"病例已结案。{summary}",
        )
        self._append_agent_response(case.id, response)
        self.db.commit()
        return response

    def _handle_message(self, case, message: str) -> CaseResponse:
        existing_structured = dict(case.structured_data or {})
        structured = self.extractor.extract(message)
        case.structured_data = structured.model_dump()
        if existing_structured.get("image_evidence"):
            case.structured_data["image_evidence"] = existing_structured["image_evidence"]
            case.structured_data["image_analysis_status"] = existing_structured.get(
                "image_analysis_status", "pending_vision_tool"
            )
            if existing_structured.get("vision_observation"):
                case.structured_data["vision_observation"] = existing_structured["vision_observation"]
        if existing_structured.get("weather_observation"):
            case.structured_data["weather_observation"] = existing_structured["weather_observation"]
        self._merge_extracted_fields(case, structured.raw)
        if structured.severity and not case.severity:
            case.severity = structured.severity
        if structured.affected_parts:
            case.affected_parts = list({*case.affected_parts, *structured.affected_parts})

        self.events.append(
            case.id,
            EventType.SYMPTOMS_EXTRACTED,
            user_input=message,
            structured_data=structured.model_dump(),
        )

        active_followup = self.followups.active_for_case(case.id)
        context = AgentDecisionContext(
            case_status=CaseStatus(case.status),
            latest_user_message=message,
            structured_symptoms=structured,
            active_followup={"id": active_followup.id} if active_followup else None,
            history_summary=[],
            available_actions=list(AgentAction),
        )
        decision = self.decision_engine.decide(context)
        self.events.append(
            case.id,
            EventType.AGENT_DECISION,
            system_output=decision.model_dump(mode="json"),
        )

        if decision.next_action == AgentAction.ASK_MORE_INFO:
            return self._ask_more_info(case, decision)
        if decision.next_action == AgentAction.COMPARE_FOLLOWUP:
            followup_input = FollowupInput(description=message)
            return self.submit_followup(case.id, followup_input, record_response=False)
        if decision.next_action == AgentAction.ESCALATE:
            return self._escalate(case, decision.reason)
        if decision.next_action == AgentAction.CLOSE_CASE:
            return self.close_case(case.id, CloseCaseInput())
        return self._diagnose_and_plan(case, decision)

    def _ask_more_info(self, case, decision) -> CaseResponse:
        transition = self.state_machine.apply(case, CaseStatus.NEED_MORE_INFO, decision.reason)
        if not transition.allowed:
            return self._escalate(case, transition.reason)

        output = {"questions": decision.questions, "reason": decision.reason}
        self.events.append(case.id, EventType.QUESTIONS_ASKED, system_output=output)
        self.events.append(
            case.id,
            EventType.STATE_CHANGED,
            system_output={"status": case.status, "reason": decision.reason},
        )
        return CaseResponse(
            case_id=case.id,
            status=CaseStatus(case.status),
            response_type="questions",
            message="为了避免误判，请先补充几个关键信息。",
            decision=AgentDecisionRead(**decision.model_dump()),
        )

    def _diagnose_and_plan(self, case, decision) -> CaseResponse:
        structured = self.extractor.extract(case.symptoms)
        entries = self.knowledge.search(structured)
        diagnosis = self.diagnosis_tool.diagnose(entries)
        case.suspected_problem = diagnosis.suspected_problem
        case.likelihood = diagnosis.likelihood

        safety_result = self.safety.check(
            SafetyContext(
                days_to_harvest=case.days_to_harvest,
                recent_pesticide_use=case.recent_pesticide_use,
                environment=case.environment,
                suspected_problem=diagnosis.suspected_problem,
                severity=case.severity or structured.severity,
                uncertain=diagnosis.likelihood in {"较低", None},
            )
        )
        self.events.append(
            case.id,
            EventType.SAFETY_CHECKED,
            system_output=safety_result.to_dict(),
        )

        if safety_result.must_escalate:
            return self._escalate(case, "安全检查要求升级人工确认")

        entry = entries[0] if entries else None
        plan = self.plan_tool.build_plan(entry, safety_result.warnings)
        case.current_plan = plan.model_dump()
        self.events.append(case.id, EventType.DIAGNOSIS_GENERATED, system_output=diagnosis.model_dump())
        self.events.append(case.id, EventType.PLAN_GENERATED, system_output=plan.model_dump())

        followup = None
        if plan.followup_after_days:
            due_date = date.today() + timedelta(days=plan.followup_after_days)
            followup = self.followups.create(case.id, due_date, plan.observation_points)
            self.reminders.create(
                ReminderCreate(
                    case_id=case.id,
                    followup_id=followup.id,
                    due_at=datetime.combine(due_date, time(hour=9)),
                    channel="in_app",
                    reason="处置方案创建的复查提醒",
                )
            )
            case.followup_date = due_date
            self.events.append(
                case.id,
                EventType.FOLLOWUP_CREATED,
                system_output={"followup_id": followup.id, "due_date": due_date.isoformat()},
            )
            self.events.append(
                case.id,
                EventType.REMINDER_CREATED,
                system_output={
                    "followup_id": followup.id,
                    "due_at": datetime.combine(due_date, time(hour=9)).isoformat(),
                    "channel": "in_app",
                },
            )

        transition = self.state_machine.apply(case, CaseStatus.FOLLOWUP_PENDING, decision.reason)
        if not transition.allowed:
            return self._escalate(case, transition.reason)

        self.events.append(
            case.id,
            EventType.STATE_CHANGED,
            system_output={"status": case.status, "reason": decision.reason},
        )
        return CaseResponse(
            case_id=case.id,
            status=CaseStatus(case.status),
            response_type="diagnosis_and_plan",
            message="已形成保守的初步判断，并创建复查计划。",
            decision=AgentDecisionRead(**decision.model_dump()),
            diagnosis=diagnosis,
            plan=plan,
            safety=SafetyResultRead(**safety_result.to_dict()),
            followup=FollowupRead.model_validate(followup) if followup else None,
        )

    def _escalate(self, case, reason: str) -> CaseResponse:
        self.state_machine.apply(case, CaseStatus.ESCALATED, reason)
        self.events.append(case.id, EventType.ESCALATED, system_output={"reason": reason})
        self.events.append(
            case.id,
            EventType.STATE_CHANGED,
            system_output={"status": case.status, "reason": reason},
        )
        return CaseResponse(
            case_id=case.id,
            status=CaseStatus(case.status),
            response_type="escalated",
            message="当前情况不适合继续仅凭通用建议处理，建议联系当地农技人员或专业人员确认。",
        )

    def _require_case(self, case_id: int):
        case = self.cases.get(case_id)
        if case is None:
            raise ValueError(f"Case not found: {case_id}")
        return case

    def _append_image_evidence(self, case, image_urls: list[str]) -> None:
        if not image_urls:
            return

        current = dict(case.structured_data or {})
        evidence = list(current.get("image_evidence", []))
        for image_url in image_urls:
            if image_url not in evidence:
                evidence.append(image_url)

        current["image_evidence"] = evidence
        vision = self.vision_tool.analyze(image_urls, context=case.symptoms)
        current["image_analysis_status"] = "analyzed" if vision.is_configured else "not_configured"
        current["vision_observation"] = vision.model_dump()
        case.structured_data = current
        self.events.append(
            case.id,
            EventType.IMAGE_EVIDENCE_ADDED,
            system_output={
                "image_count": len(image_urls),
                "analysis_status": current["image_analysis_status"],
                "note": "图片已作为工具观察进入 Case Memory；最终判断仍由编排器、安全检查和状态机约束。",
            },
            structured_data={"image_urls": image_urls},
        )
        self.events.append(
            case.id,
            EventType.VISION_ANALYZED,
            system_output=vision.model_dump(),
            structured_data={"image_urls": image_urls},
        )

    def _observe_weather(self, case, message: str) -> None:
        location = self._extract_location(case, message)
        observation = self.weather_tool.observe(location=location, user_description=message)
        if not observation.risk_signals and not observation.is_configured:
            return

        current = dict(case.structured_data or {})
        current["weather_observation"] = observation.model_dump()
        case.structured_data = current
        if observation.risk_signals and not case.recent_weather:
            case.recent_weather = "；".join(observation.risk_signals)
        self.events.append(
            case.id,
            EventType.WEATHER_OBSERVED,
            system_output=observation.model_dump(),
        )

    def _extract_location(self, case, message: str) -> str:
        if case.environment:
            return case.environment
        if "大棚" in message or "棚" in message:
            return "用户描述的大棚环境"
        if "露天" in message or "露地" in message:
            return "用户描述的露地环境"
        return "用户未提供地点"

    def _append_user_message(self, case_id: int, message: str, image_urls: list[str]) -> None:
        self.events.append(
            case_id,
            EventType.USER_MESSAGE,
            user_input=message,
            structured_data={"image_urls": image_urls} if image_urls else {},
        )

    def _append_agent_response(self, case_id: int, response: CaseResponse) -> None:
        self.events.append(
            case_id,
            EventType.AGENT_RESPONSE,
            system_output=response.model_dump(mode="json"),
        )

    def _merge_extracted_fields(self, case, raw: dict) -> None:
        if raw.get("growth_stage") and not case.growth_stage:
            case.growth_stage = raw["growth_stage"]
        if raw.get("recent_weather") and not case.recent_weather:
            case.recent_weather = raw["recent_weather"]
        if raw.get("days_to_harvest") is not None and case.days_to_harvest is None:
            case.days_to_harvest = raw["days_to_harvest"]
        if raw.get("environment") and not case.environment:
            case.environment = raw["environment"]
        if raw.get("recent_pesticide_use") and not case.recent_pesticide_use:
            case.recent_pesticide_use = raw["recent_pesticide_use"]
        if raw.get("recent_fertilizer_use") and not case.recent_fertilizer_use:
            case.recent_fertilizer_use = raw["recent_fertilizer_use"]

    def _state_for_trend(self, trend: FollowupTrend) -> CaseStatus:
        if trend == FollowupTrend.IMPROVING:
            return CaseStatus.IMPROVING
        if trend == FollowupTrend.WORSENING:
            return CaseStatus.ESCALATED
        if trend == FollowupTrend.NEEDS_HUMAN_CONFIRMATION:
            return CaseStatus.ESCALATED
        if trend == FollowupTrend.INSUFFICIENT_INFO:
            return CaseStatus.NEED_MORE_INFO
        return CaseStatus.FOLLOWUP_REVIEW

    def _followup_message(self, trend: FollowupTrend) -> str:
        if trend == FollowupTrend.IMPROVING:
            return "复查显示症状趋于好转，可继续短期观察；若持续无新症状，可考虑结案。"
        if trend == FollowupTrend.WORSENING:
            return "复查显示症状正在扩展或恶化，建议升级为人工确认。"
        if trend == FollowupTrend.INSUFFICIENT_INFO:
            return "复查信息不足，请补充是否有新病斑、是否扩大、是否扩展到新部位或果实。"
        return "复查未显示明显变化，建议继续观察并按原复查清单记录。"

    def _make_title(self, symptoms: str) -> str:
        if "果实" in symptoms or "底部发黑" in symptoms:
            return "番茄果实异常问题"
        if "小白虫" in symptoms or "飞虫" in symptoms:
            return "番茄叶背虫害问题"
        if "斑" in symptoms:
            return "番茄叶片斑点问题"
        return "番茄异常病例"
