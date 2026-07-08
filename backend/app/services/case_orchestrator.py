from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from enum import Enum
import re

from typing import Any, Callable

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.decision_engine import AgentDecisionEngine, AgentDecisionError
from app.domain.enums import AgentAction, CaseStatus, EventType, FollowupTrend
from app.domain.safety import SafetyChecker, SafetyContext
from app.domain.state_machine import StateMachine
from app.repositories.case_repository import CaseRepository
from app.repositories.event_repository import EventRepository
from app.repositories.followup_repository import FollowupRepository
from app.repositories.reminder_repository import ReminderRepository
from app.schemas.agent import AgentDecisionContext, StructuredSymptoms
from app.schemas.cases import (
    AgentDecisionRead,
    CaseResponse,
    ClosedLoopAdvice,
    CloseCaseInput,
    CreateCaseInput,
    DiagnosisRead,
    FollowupInput,
    FollowupRead,
    PlanRead,
    ReplyInput,
    SafetyResultRead,
)
from app.tools.calendar_reminder_tool import CalendarReminderTool
from app.tools.date_tool import DateTool
from app.tools.location_tool import LocationTool
from app.tools.response_composer import ResponseComposer
from app.tools.registry import ToolRegistry
from app.tools.semantic_observation_tool import SemanticObservationTool
from app.tools.vision_tool import VisionTool
from app.tools.weather_tool import WeatherTool


class CaseOrchestrator:
    def __init__(self, db: Session):
        self.db = db
        self.cases = CaseRepository(db)
        self.events = EventRepository(db)
        self.followups = FollowupRepository(db)
        self.reminders = ReminderRepository(db)
        self.decision_engine = AgentDecisionEngine()
        self.response_composer = ResponseComposer()
        self.semantic_observation_tool = SemanticObservationTool()
        self.vision_tool = VisionTool()
        self.weather_tool = WeatherTool()
        self.location_tool = LocationTool()
        self.date_tool = DateTool()
        self.calendar_reminder_tool = CalendarReminderTool(self.followups, self.reminders)
        self.tool_registry = ToolRegistry()
        self.tool_registry.register(self.date_tool)
        self.tool_registry.register(self.semantic_observation_tool)
        self.tool_registry.register(self.location_tool)
        self.tool_registry.register(self.weather_tool)
        self.state_machine = StateMachine()
        self.safety = SafetyChecker()

    def create_case(self, data: CreateCaseInput) -> CaseResponse:
        title = self._make_title(data.symptoms)
        case = self.cases.create(data, title=title)
        self.events.append(case.id, EventType.CASE_CREATED, user_input=data.symptoms)
        self._append_user_message(case.id, data.symptoms, data.image_urls)
        self._observe_date(case)
        self._append_image_evidence(case, data.image_urls)
        self._observe_semantics(case, data.symptoms)
        self._observe_weather(
            case,
            data.symptoms,
            data.latitude,
            data.longitude,
            data.location_label,
            data.location_source,
            data.location_error,
        )

        response = self._handle_message(case, data.symptoms)
        response = self._compose_response(case.id, response)
        self._append_agent_response(case.id, response)
        self.db.commit()
        return response

    def reply_to_case(self, case_id: int, data: ReplyInput) -> CaseResponse:
        case = self._require_case(case_id)
        case.symptoms = f"{case.symptoms}\n{data.message}".strip()
        self._append_user_message(case.id, data.message, data.image_urls)
        self._observe_date(case)
        self._append_image_evidence(case, data.image_urls)
        self._observe_semantics(case, data.message)
        self._observe_weather(
            case,
            data.message,
            data.latitude,
            data.longitude,
            data.location_label,
            data.location_source,
            data.location_error,
        )
        response = self._handle_message(case, data.message)
        response = self._compose_response(case.id, response)
        self._append_agent_response(case.id, response)
        self.db.commit()
        return response

    def submit_followup(
        self,
        case_id: int,
        data: FollowupInput,
        record_response: bool = True,
        decision=None,
    ) -> CaseResponse:
        case = self._require_case(case_id)
        active = self.followups.active_for_case(case.id)
        self.events.append(case.id, EventType.FOLLOWUP_SUBMITTED, user_input=data.description)

        semantic = (case.structured_data or {}).get("semantic_observation") or {}
        if not semantic.get("followup_trend"):
            self._observe_semantics(case, data.description)
            semantic = (case.structured_data or {}).get("semantic_observation") or {}
        trend = self._trend_from_decision_or_semantic(decision, semantic)
        evidence = (
            getattr(decision, "followup_evidence", None)
            or semantic.get("followup_evidence")
            or semantic.get("uncertainties")
            or ["Agent 已根据本轮语义和决策判断复查趋势。"]
        )
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
            advice=self._build_followup_advice(trend, case, active),
        )
        response = self._compose_response(case.id, response)
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
        structured = self._semantic_structured_symptoms(message, existing_structured)
        vision_observation = existing_structured.get("vision_observation")
        fused_structured = self._fuse_observations(structured, vision_observation, case)
        case.structured_data = fused_structured.model_dump()
        if existing_structured.get("image_evidence"):
            case.structured_data["image_evidence"] = existing_structured["image_evidence"]
            case.structured_data["image_analysis_status"] = existing_structured.get(
                "image_analysis_status", "pending_vision_tool"
            )
            if vision_observation:
                case.structured_data["vision_observation"] = vision_observation
                case.structured_data["multimodal_observation"] = self._build_multimodal_observation(
                    structured, fused_structured, vision_observation
                )
        if existing_structured.get("weather_observation"):
            case.structured_data["weather_observation"] = existing_structured["weather_observation"]
        if existing_structured.get("location_observation"):
            case.structured_data["location_observation"] = existing_structured["location_observation"]
        if existing_structured.get("date_observation"):
            case.structured_data["date_observation"] = existing_structured["date_observation"]
        if existing_structured.get("semantic_observation"):
            case.structured_data["semantic_observation"] = existing_structured["semantic_observation"]
        self._merge_extracted_fields(case, fused_structured.raw)
        if structured.severity and not case.severity:
            case.severity = structured.severity
        if fused_structured.affected_parts:
            case.affected_parts = list({*case.affected_parts, *fused_structured.affected_parts})

        self.events.append(
            case.id,
            EventType.SYMPTOMS_EXTRACTED,
            user_input=message,
            structured_data=fused_structured.model_dump(),
        )

        active_followup = self.followups.active_for_case(case.id)
        context = AgentDecisionContext(
            case_status=CaseStatus(case.status),
            latest_user_message=message,
            structured_symptoms=fused_structured,
            vision_observation=vision_observation,
            multimodal_observation=case.structured_data.get("multimodal_observation"),
            semantic_observation=case.structured_data.get("semantic_observation"),
            weather_observation=case.structured_data.get("weather_observation"),
            date_observation=case.structured_data.get("date_observation"),
            active_followup=self._followup_context(active_followup) if active_followup else None,
            history_summary=self._history_summary(case.id),
            available_actions=list(AgentAction),
        )
        try:
            decision = self.decision_engine.decide(context)
        except AgentDecisionError as exc:
            self.events.append(
                case.id,
                EventType.AGENT_DECISION,
                system_output={
                    "decision_source": "llm_error",
                    "error": str(exc),
                    "trace": {
                        "observe": {
                            "case_status": context.case_status.value,
                            "latest_user_message": context.latest_user_message,
                            "missing_fields": context.structured_symptoms.missing_fields,
                            "affected_parts": context.structured_symptoms.affected_parts,
                            "symptoms": context.structured_symptoms.symptoms,
                            "vision_status": (context.vision_observation or {}).get("status"),
                "weather_status": bool(context.weather_observation),
                "weather_risk_signals": (context.weather_observation or {}).get("risk_signals", []),
                "today": (context.date_observation or {}).get("today"),
                            "active_followup": bool(context.active_followup),
                        },
                        "decide": {
                            "source": "llm_error",
                            "next_action": None,
                            "requested_state": CaseStatus.ESCALATED.value,
                            "confidence": "none",
                            "reason": str(exc),
                            "fallback_reason": None,
                            "observations_used": [],
                        },
                        "act": {"planned_tools": ["StateMachine", "EventMemory"], "questions": []},
                        "guard": {"guardrails": ["LLM 决策失败时不静默回退为规则答案"]},
                        "memory": {"will_write_events": [EventType.AGENT_DECISION.value, EventType.ESCALATED.value]},
                    },
                },
            )
            return self._escalate(case, str(exc))
        self.events.append(
            case.id,
            EventType.AGENT_DECISION,
            system_output={
                **decision.model_dump(mode="json"),
                "trace": self._build_decision_trace(context, decision),
            },
        )

        if decision.next_action == AgentAction.ASK_MORE_INFO:
            return self._ask_more_info(case, decision)
        if decision.next_action == AgentAction.COMPARE_FOLLOWUP:
            followup_input = FollowupInput(description=message)
            return self.submit_followup(case.id, followup_input, record_response=False, decision=decision)
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
            message="现在还不适合直接下判断，我先帮你把关键信息补齐。",
            decision=AgentDecisionRead(**decision.model_dump()),
            advice=self._build_more_info_advice(case, decision),
        )

    def _diagnose_and_plan(self, case, decision) -> CaseResponse:
        existing_structured = dict(case.structured_data or {})
        structured = StructuredSymptoms.model_validate(
            {
                "crop": existing_structured.get("crop", "番茄"),
                "affected_parts": existing_structured.get("affected_parts", []),
                "symptoms": existing_structured.get("symptoms", []),
                "possible_categories": existing_structured.get("possible_categories", []),
                "missing_fields": existing_structured.get("missing_fields", []),
                "severity": existing_structured.get("severity"),
                "raw": existing_structured.get("raw", {}),
            }
        )
        likely_causes = decision.likely_causes or ["信息不足"]
        diagnosis = DiagnosisRead(
            suspected_problem=likely_causes[0] if likely_causes else None,
            likelihood=decision.confidence_label or decision.confidence,
            evidence=decision.diagnosis_evidence or decision.observations_used,
            confusions=[],
        )
        case.suspected_problem = diagnosis.suspected_problem
        case.likelihood = diagnosis.likelihood

        weather_observation = existing_structured.get("weather_observation") or {}
        safety_context = SafetyContext(
            days_to_harvest=case.days_to_harvest,
            recent_pesticide_use=case.recent_pesticide_use,
            environment=case.environment,
            suspected_problem=diagnosis.suspected_problem,
            severity=decision.severity_label or case.severity or structured.severity,
            uncertain=diagnosis.likelihood in {"较低", None},
            weather_risk_signals=[],
        )
        safety_result = self._call_tool(
            case.id,
            "SafetyChecker",
            lambda: self.safety.check(safety_context),
            input_summary={
                "days_to_harvest": case.days_to_harvest,
                "suspected_problem": diagnosis.suspected_problem,
                "severity": decision.severity_label or case.severity or structured.severity,
            },
        )
        self.events.append(
            case.id,
            EventType.SAFETY_CHECKED,
            system_output=safety_result.to_dict(),
        )

        if safety_result.must_escalate:
            return self._escalate(case, "安全检查要求升级人工确认")

        plan = PlanRead(
            summary=decision.plain_summary or f"当前更像{diagnosis.suspected_problem or '番茄异常'}，建议按保守方案处理。",
            immediate_actions=decision.immediate_actions,
            observation_points=decision.observation_points,
            escalation_conditions=decision.escalation_conditions,
            safety_warnings=[
                *(safety_result.warnings or []),
                *([decision.chemical_safety_note] if decision.chemical_safety_note else []),
                *([decision.harvest_safety_note] if decision.harvest_safety_note else []),
            ],
            followup_after_days=decision.followup_after_days,
        )
        case.current_plan = plan.model_dump()
        self.events.append(case.id, EventType.DIAGNOSIS_GENERATED, system_output=diagnosis.model_dump())
        self.events.append(case.id, EventType.PLAN_GENERATED, system_output=plan.model_dump())

        followup = None
        if plan.followup_after_days:
            today_text = (existing_structured.get("date_observation") or {}).get("today")
            today = date.fromisoformat(today_text) if today_text else date.today()
            due_date = today + timedelta(days=plan.followup_after_days)
            reminder_result = self._call_tool(
                case.id,
                "CalendarReminderTool",
                lambda: self.calendar_reminder_tool.schedule_followup(
                    case_id=case.id,
                    due_date=due_date,
                    checklist=plan.observation_points,
                    reason="处置方案更新后的复查提醒"
                    if self.followups.active_for_case(case.id)
                    else "处置方案创建的复查提醒",
                ),
                input_summary={
                    "due_date": due_date.isoformat(),
                    "checklist_count": len(plan.observation_points),
                },
            )
            followup = self.followups.get(reminder_result.followup_id)
            self.events.append(
                case.id,
                EventType.FOLLOWUP_CREATED,
                system_output=reminder_result.model_dump(),
            )
            case.followup_date = due_date
            self.events.append(
                case.id,
                EventType.REMINDER_CREATED,
                system_output=reminder_result.model_dump(),
            )

        transition = self.state_machine.apply(case, CaseStatus.FOLLOWUP_PENDING, decision.reason)
        if not transition.allowed:
            return self._escalate(case, transition.reason)

        self.events.append(
            case.id,
            EventType.STATE_CHANGED,
            system_output={"status": case.status, "reason": decision.reason},
        )
        advice = self._build_diagnosis_advice(
            case=case,
            structured=structured,
            category=decision.problem_category,
            diagnosis=diagnosis,
            plan=plan,
            safety_result=safety_result,
            followup=followup,
        )
        return CaseResponse(
            case_id=case.id,
            status=CaseStatus(case.status),
            response_type="diagnosis_and_plan",
            message=advice.plain_summary,
            decision=AgentDecisionRead(**decision.model_dump()),
            diagnosis=diagnosis,
            plan=plan,
            safety=SafetyResultRead(**safety_result.to_dict()),
            followup=FollowupRead.model_validate(followup) if followup else None,
            advice=advice,
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
            advice=ClosedLoopAdvice(
                information_sufficient=False,
                problem_category=None,
                severity="偏高或不确定",
                action_mode="建议人工确认",
                chemical_advice="不建议仅凭当前信息自行用药。",
                harvest_safety="如果临近采收，更要先核对采前安全间隔期。",
                plain_summary="当前情况不适合继续只靠通用建议处理，建议找当地农技人员或专业人员确认。",
                immediate_actions=["先隔离或标记问题植株", "拍照记录变化", "暂停自行叠加用药或施肥"],
                observation_points=["是否继续扩展", "是否影响果实", "是否多株同时发生"],
                escalation_conditions=["症状继续加重", "果实受害", "整株萎蔫或多株同时发病"],
                followup_timing="人工确认后再安排复查",
                followup_if_better=["继续观察 3-5 天", "无新症状后可考虑结案"],
                followup_if_worse=["停止单纯观察", "尽快人工确认"],
                process_record=["已记录用户输入", "已记录 Agent 升级判断", "已记录状态变化"],
            ),
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
        vision = self._call_tool(
            case.id,
            "VisionTool",
            lambda: self.vision_tool.analyze(image_urls, context=case.symptoms),
            input_summary={"image_count": len(image_urls), "has_context": bool(case.symptoms)},
        )
        current["image_analysis_status"] = (
            vision.status if vision.status != "not_configured" or not vision.is_configured else "analyzed"
        )
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

    def _observe_date(self, case) -> None:
        observation = self._call_tool(
            case.id,
            "DateTool",
            lambda: self.tool_registry.call("DateTool"),
            input_summary={"timezone": "Asia/Shanghai"},
        )
        current = dict(case.structured_data or {})
        current["date_observation"] = observation.model_dump()
        case.structured_data = current
        self.events.append(
            case.id,
            EventType.DATE_OBSERVED,
            system_output=observation.model_dump(),
        )

    def _observe_semantics(self, case, message: str) -> None:
        active_followup = self.followups.active_for_case(case.id)
        observation = self._call_tool(
            case.id,
            "SemanticObservationTool",
            lambda: self.tool_registry.call(
                "SemanticObservationTool",
                message=message,
                case_memory={
                    "status": case.status,
                    "suspected_problem": case.suspected_problem,
                    "growth_stage": case.growth_stage,
                    "days_to_harvest": case.days_to_harvest,
                    "affected_parts": case.affected_parts,
                    "recent_weather": case.recent_weather,
                    "severity": case.severity,
                    "current_plan_summary": (case.current_plan or {}).get("summary")
                    if case.current_plan
                    else None,
                },
                active_followup=self._followup_context(active_followup) if active_followup else None,
                date_observation=(case.structured_data or {}).get("date_observation"),
                history_summary=self._history_summary(case.id),
            ),
            input_summary={
                "message_length": len(message),
                "active_followup": bool(active_followup),
                "has_vision": bool((case.structured_data or {}).get("vision_observation")),
            },
        )
        current = dict(case.structured_data or {})
        current["semantic_observation"] = observation.model_dump(mode="json")
        case.structured_data = current

    def _observe_weather(
        self,
        case,
        message: str,
        latitude: float | None = None,
        longitude: float | None = None,
        location_label: str | None = None,
        location_source: str | None = None,
        location_error: str | None = None,
    ) -> None:
        semantic = (case.structured_data or {}).get("semantic_observation") or {}
        raw = self._semantic_raw(semantic)
        explicit_location = raw.get("location_text")
        current_structured = dict(case.structured_data or {})
        previous_location = current_structured.get("location_observation") or {}
        previous_weather = current_structured.get("weather_observation") or {}
        is_first_location_turn = not previous_location and not previous_weather

        if is_first_location_turn or explicit_location:
            location_observation = self._call_tool(
                case.id,
                "LocationTool",
                lambda: self.tool_registry.call(
                    "LocationTool",
                    fallback_location=self._extract_location(case, message),
                    user_message=message,
                    browser_latitude=latitude,
                    browser_longitude=longitude,
                    browser_location_label=location_label,
                    browser_location_source=location_source,
                    browser_location_error=location_error,
                    explicit_location=explicit_location,
                    previous_location=previous_location.get("location") or previous_weather.get("location"),
                    previous_location_source=previous_location.get("location_source")
                    or previous_weather.get("location_source"),
                    previous_adcode=previous_location.get("adcode") or previous_weather.get("adcode"),
                ),
                input_summary={
                    "turn_scope": "first_or_user_location_update",
                    "explicit_location": explicit_location,
                    "browser_location_label": location_label,
                    "browser_location_source": location_source,
                    "has_coordinates": latitude is not None and longitude is not None,
                },
            )
        else:
            location_observation = self._location_observation_from_memory(
                previous_location,
                previous_weather,
            )
        location = location_observation.location
        resolved_source = location_observation.location_source
        latitude = location_observation.latitude
        longitude = location_observation.longitude
        location_error = location_observation.location_error
        current = dict(case.structured_data or {})
        location_dump = location_observation.model_dump()
        location_dump["should_confirm_with_user"] = bool(is_first_location_turn or explicit_location)
        current["location_observation"] = location_dump
        case.structured_data = current

        observation = self._call_tool(
            case.id,
            "WeatherTool",
            lambda: self.tool_registry.call(
                "WeatherTool",
                location=location,
                adcode=location_observation.adcode,
                latitude=latitude,
                longitude=longitude,
                location_source=resolved_source,
                location_error=location_error,
            ),
            input_summary={
                "location": location,
                "location_source": resolved_source,
                "adcode": location_observation.adcode,
                "location_error": location_error,
                "message_length": len(message),
                "has_coordinates": latitude is not None and longitude is not None,
            },
        )
        if not observation.risk_signals and not observation.is_configured and not observation.uncertainties:
            return

        current = dict(case.structured_data or {})
        weather_dump = observation.model_dump()
        weather_dump["should_confirm_location_with_user"] = bool(is_first_location_turn or explicit_location)
        current["weather_observation"] = weather_dump
        case.structured_data = current
        if observation.status == "live_weather":
            weather_text = " ".join(
                str(item)
                for item in [observation.weather, observation.temperature, observation.humidity]
                if item not in (None, "")
            )
            if weather_text:
                case.recent_weather = weather_text
        self.events.append(
            case.id,
            EventType.WEATHER_OBSERVED,
            system_output=observation.model_dump(),
        )

    def _location_observation_from_memory(
        self,
        previous_location: dict,
        previous_weather: dict,
    ):
        from app.tools.location_tool import LocationObservation

        location = previous_location or previous_weather
        return LocationObservation(
            location=location.get("location") or "用户未提供地点",
            location_source="case_memory_user_location",
            adcode=location.get("adcode"),
            province=location.get("province"),
            city=location.get("city"),
            district=location.get("district"),
            latitude=location.get("latitude"),
            longitude=location.get("longitude"),
            location_error=location.get("location_error"),
            requires_confirmation=location.get("requires_confirmation", True),
            note="沿用本病例首轮确认的种植地点；本轮只刷新天气。",
            provider=location.get("provider", "amap"),
            language_confidence=location.get("language_confidence"),
            evidence=location.get("evidence", []),
            uncertainties=location.get("uncertainties", []),
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

    def _call_tool(
        self,
        case_id: int,
        tool_name: str,
        caller: Callable[[], Any],
        input_summary: dict | None = None,
    ) -> Any:
        try:
            result = caller()
        except Exception as exc:
            self.events.append(
                case_id,
                EventType.TOOL_CALLED,
                system_output={
                    "tool": tool_name,
                    "ok": False,
                    "input_summary": input_summary or {},
                    "error": str(exc),
                },
            )
            raise

        self.events.append(
            case_id,
            EventType.TOOL_CALLED,
            system_output={
                "tool": tool_name,
                "ok": True,
                "input_summary": input_summary or {},
                "output": self._serialize_tool_output(result),
            },
        )
        return result

    def _serialize_tool_output(self, result: Any) -> Any:
        if isinstance(result, BaseModel):
            return result.model_dump(mode="json")
        if is_dataclass(result) and not isinstance(result, type):
            return self._serialize_tool_output(asdict(result))
        if isinstance(result, Enum):
            return result.value
        if isinstance(result, date | datetime):
            return result.isoformat()
        if isinstance(result, tuple):
            return [self._serialize_tool_output(item) for item in result]
        if isinstance(result, list):
            return [self._serialize_tool_output(item) for item in result]
        if isinstance(result, dict):
            return {key: self._serialize_tool_output(value) for key, value in result.items()}
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        return result

    def _compose_response(self, case_id: int, response: CaseResponse) -> CaseResponse:
        response.message = self._call_tool(
            case_id,
            "ResponseComposer",
            lambda: self.response_composer.compose(response),
            input_summary={
                "response_type": response.response_type,
                "user_intent": response.decision.user_intent if response.decision else None,
            },
        )
        return response

    def _followup_context(self, followup) -> dict:
        today = date.today()
        days_until_due = (followup.due_date - today).days
        return {
            "id": followup.id,
            "due_date": followup.due_date.isoformat(),
            "today": today.isoformat(),
            "days_until_due": days_until_due,
            "is_due": days_until_due <= 0,
            "checklist": followup.checklist,
        }

    def _history_summary(self, case_id: int, limit: int = 8) -> list[dict]:
        detail = self.cases.get_detail(case_id)
        if detail is None:
            return []
        summary = []
        for event in detail.events[-limit:]:
            summary.append(
                {
                    "event_type": event.event_type,
                    "user_input": event.user_input,
                    "system_output_keys": list((event.system_output or {}).keys())[:8],
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                }
            )
        return summary

    def _build_more_info_advice(self, case, decision) -> ClosedLoopAdvice:
        missing = ", ".join((case.structured_data or {}).get("missing_fields", [])) or "关键信息"
        return ClosedLoopAdvice(
            information_sufficient=False,
            problem_category=self._category_from_structured(case.structured_data or {}),
            severity=case.severity or "暂时无法判断",
            action_mode="先补充信息，暂不直接处理",
            chemical_advice="现在信息不够，不建议直接用药。",
            harvest_safety=(
                f"距离采收约 {case.days_to_harvest} 天，后续会优先检查采收安全。"
                if case.days_to_harvest is not None
                else "还不知道距离采收多久，涉及用药前必须先确认。"
            ),
            plain_summary=f"我现在还缺少{missing}，直接判断容易误导你。先回答下面几个问题，我再决定下一步。",
            immediate_actions=["先拍清楚异常部位和整株状态", "暂时不要自行混用药或加肥", "把明显异常的叶片/果实单独标记，方便复查对比"],
            observation_points=["异常主要在哪个部位", "斑点、虫体或霉层是否继续增加", "是否影响果实或多株同时发生"],
            escalation_conditions=["症状快速扩展", "果实受害", "整株萎蔫", "多株同时发病"],
            followup_timing="补充信息后再决定是否创建复查任务",
            followup_if_better=["如果补充前症状已减轻，也请说明做过哪些处理"],
            followup_if_worse=["如果变多、扩散到新部位或影响果实，请优先说明这些变化"],
            process_record=["已创建病例", "已记录原始描述", "已记录需要补充的问题"],
            environment_confirmation=self._environment_confirmation(case),
        )

    def _build_diagnosis_advice(
        self,
        case,
        structured: StructuredSymptoms,
        category: str | None,
        diagnosis: DiagnosisRead,
        plan: PlanRead,
        safety_result,
        followup,
    ) -> ClosedLoopAdvice:
        category = category or self._category_from_structured(case.structured_data or {})
        severity = self._severity_label(case.severity or structured.severity, safety_result.risk_level)
        action_mode = self._action_mode(severity, safety_result.risk_level)
        harvest_safety = self._harvest_safety_text(case.days_to_harvest, safety_result.warnings)
        chemical_advice = self._chemical_advice_text(safety_result)
        followup_timing = (
            f"{followup.due_date.isoformat()} 复查，重点看有没有新斑点、是否扩散、果实是否受影响。"
            if followup
            else "暂未创建复查任务。"
        )
        problem = diagnosis.suspected_problem or "当前异常"
        likelihood = diagnosis.likelihood or "不确定"
        plain_summary = (
            f"从你提供的信息看，当前更像{problem}，把握程度是{likelihood}。"
            f"现在建议{action_mode}，我已经把处理和复查记录进这个病例。"
        )
        if safety_result.risk_level == "high":
            plain_summary = "当前风险偏高，不建议继续只靠通用建议处理，最好尽快人工确认。"

        return ClosedLoopAdvice(
            information_sufficient=True,
            problem_category=category,
            severity=severity,
            action_mode=action_mode,
            chemical_advice=chemical_advice,
            harvest_safety=harvest_safety,
            plain_summary=plain_summary,
            immediate_actions=plan.immediate_actions,
            observation_points=plan.observation_points,
            escalation_conditions=plan.escalation_conditions,
            followup_timing=followup_timing,
            followup_if_better=[
                "如果没有新增斑点/虫体，继续保持通风和稳定管理。",
                "再观察 3-5 天，如果仍然稳定，可以考虑结案。",
            ],
            followup_if_worse=[
                "如果数量明显增加、扩散到上部叶片或果实，不要继续单纯观察。",
                "建议升级为人工确认，并带上本病例记录和照片变化。",
            ],
            process_record=[
                "已记录用户描述和图片证据",
                "已记录结构化症状和 Agent 决策",
                "已记录安全检查、处置方案和复查提醒",
            ],
            environment_confirmation=self._environment_confirmation(case),
        )

    def _build_followup_advice(self, trend: FollowupTrend, case, followup) -> ClosedLoopAdvice:
        is_better = trend == FollowupTrend.IMPROVING
        is_worse = trend in {FollowupTrend.WORSENING, FollowupTrend.NEEDS_HUMAN_CONFIRMATION}
        action_mode = "继续观察" if is_better else "升级确认" if is_worse else "补充复查信息"
        plain_summary = self._followup_message(trend)
        return ClosedLoopAdvice(
            information_sufficient=trend != FollowupTrend.INSUFFICIENT_INFO,
            problem_category=self._category_from_structured(case.structured_data or {}),
            severity="趋于好转" if is_better else "可能加重" if is_worse else "暂不明确",
            action_mode=action_mode,
            chemical_advice="复查阶段仍不建议自行叠加或混用药。",
            harvest_safety=self._harvest_safety_text(case.days_to_harvest, []),
            plain_summary=plain_summary,
            immediate_actions=(
                ["继续保持通风", "维持稳定浇水", "暂时不要增加新的处理动作"]
                if is_better
                else ["停止单纯观察", "拍摄同一部位对比照片", "联系当地农技人员或有经验人员确认"]
                if is_worse
                else ["补充是否有新斑点、是否扩大、是否扩散到新部位、果实是否受影响"]
            ),
            observation_points=(case.current_plan or {}).get("observation_points", []),
            escalation_conditions=(case.current_plan or {}).get("escalation_conditions", []),
            followup_timing="如继续观察，建议 3 天内再次复查。" if not is_worse else "建议尽快人工确认后再复查。",
            followup_if_better=["继续观察 3-5 天", "无新症状后可点击结案"],
            followup_if_worse=["升级人工确认", "不要继续只按原方案处理"],
            process_record=[
                "已记录本次复查描述",
                f"已判断复查趋势：{trend.value}",
                "已更新病例状态和提醒记录",
            ],
            environment_confirmation=self._environment_confirmation(case),
        )

    def _semantic_structured_symptoms(self, message: str, existing_structured: dict) -> StructuredSymptoms:
        semantic = existing_structured.get("semantic_observation") or {}
        if semantic.get("is_configured") and semantic.get("status") == "analyzed":
            raw = self._semantic_raw(semantic)
            return StructuredSymptoms(
                affected_parts=self._unique([str(item) for item in semantic.get("affected_parts", [])]),
                symptoms=self._unique([str(item) for item in semantic.get("symptoms", [])]),
                possible_categories=self._unique([str(item) for item in semantic.get("possible_categories", [])]),
                missing_fields=[],
                severity=semantic.get("severity"),
                raw=raw,
            )
        return StructuredSymptoms(
            affected_parts=[],
            symptoms=[],
            possible_categories=[],
            missing_fields=[],
            severity=None,
            raw={
                "semantic_observation_status": semantic.get("status", "not_run"),
                "semantic_uncertainties": semantic.get("uncertainties", []),
            },
        )

    def _semantic_raw(self, semantic: dict) -> dict:
        raw: dict[str, Any] = {}
        mapping = {
            "severity": "severity",
        }
        for source_key, target_key in mapping.items():
            value = semantic.get(source_key)
            if value not in (None, "", [], {}):
                raw[target_key] = value
        if semantic.get("mentioned_problems"):
            raw["mentioned_problems"] = self._unique([str(item) for item in semantic.get("mentioned_problems", [])])
        if semantic.get("corrections"):
            raw["corrections"] = semantic.get("corrections")
        if semantic.get("is_followup_report"):
            raw["is_followup_report"] = True
            raw["followup_trend"] = semantic.get("followup_trend")
            raw["followup_evidence"] = semantic.get("followup_evidence", [])
        raw["semantic_user_intent"] = semantic.get("user_intent", "unknown")
        raw["semantic_confidence"] = semantic.get("confidence", "low")
        return raw

    def _environment_confirmation(self, case) -> str | None:
        weather = (case.structured_data or {}).get("weather_observation") or {}
        if not weather:
            return None

        location = weather.get("location") or "未确认地点"
        source = weather.get("location_source") or "unknown"
        status = weather.get("status") or "manual_only"
        temperature = weather.get("current_temperature_c")
        humidity = weather.get("current_relative_humidity")
        weather_bits = []
        if temperature is not None:
            weather_bits.append(f"温度约 {temperature}℃")
        if humidity is not None:
            weather_bits.append(f"湿度约 {humidity}%")
        if weather.get("risk_signals"):
            weather_bits.append("；".join(weather.get("risk_signals", [])[:2]))
        weather_text = "，".join(weather_bits) if weather_bits else "暂未拿到实时天气，只参考了你的文字描述"

        if source == "user_explicit":
            return f"我按你明确提供的地点「{location}」和天气信息来判断：{weather_text}。"
        if source == "case_memory_user_location":
            return f"我继续按这个病例之前确认的地点「{location}」来判断：{weather_text}。如果植株不在那里，请告诉我实际地点。"
        if status == "live_weather":
            should_confirm = weather.get("should_confirm_location_with_user", True)
            if not should_confirm and source in {"case_memory_user_location", "user_explicit"}:
                return None
            if source in {"browser", "browser_failed", "browser_unavailable"}:
                return f"我这轮按客户端定位附近「{location}」的实时天气来判断：{weather_text}。如果番茄不在你当前位置，请告诉我实际地点和最近天气。"
            if source == "amap_ip":
                return f"我这轮按 IP 定位推断的「{location}」实时天气来判断：{weather_text}。IP 定位通常只到城市级，如果植株不在这里，请直接告诉我实际地点。"
            return f"我这轮按「{location}」的实时天气来判断：{weather_text}。如果地点不对，请告诉我实际种植地点。"
        return f"地点/天气还没有确认，我暂按「{location}」和你文字里的天气线索判断。若植株不在当前位置，请直接补充实际地点和最近天气。"

    def _category_from_structured(self, structured_data: dict) -> str | None:
        categories = structured_data.get("possible_categories") or []
        if categories:
            return str(categories[0])
        problem = str(structured_data.get("suspected_problem") or "")
        for category in ["病害", "虫害", "缺素", "肥害", "环境问题", "生理性问题"]:
            if category in problem:
                return category
        return None

    def _severity_label(self, severity: str | None, risk_level: str) -> str:
        if risk_level == "high":
            return "偏重，需要人工确认"
        if severity:
            return severity
        if risk_level == "medium":
            return "轻到中等，需谨慎"
        return "轻度或早期可能性较大"

    def _action_mode(self, severity: str, risk_level: str) -> str:
        if risk_level == "high" or "严重" in severity or "偏重" in severity:
            return "尽快人工确认"
        if "轻" in severity or risk_level == "low":
            return "先做非化学处理并按期复查"
        return "先处理关键风险点，再短期复查"

    def _chemical_advice_text(self, safety_result) -> str:
        if not safety_result.chemical_detail_allowed:
            return "不提供具体药剂、剂量、兑水比例或施药频次。优先按非化学措施处理；如确需用药，请核对当地登记标签和采前安全间隔期。"
        return "可在专业人员或当地登记标签指导下考虑药剂，但本系统仍不直接给出处方。"

    def _harvest_safety_text(self, days_to_harvest: int | None, warnings: list[str]) -> str:
        if days_to_harvest is None:
            return "还不知道距离采收多久；涉及用药前必须先确认采收时间。"
        if days_to_harvest <= 7:
            return f"距离采收约 {days_to_harvest} 天，属于临近采收，优先非化学处理，不给具体用药处方。"
        if warnings:
            return "已做采收和用药安全检查，请按安全提醒执行。"
        return f"距离采收约 {days_to_harvest} 天，仍需避免自行混配或超范围用药。"

    def _merge_extracted_fields(self, case, raw: dict) -> None:
        corrections = raw.get("corrections") or {}
        if corrections.get("growth_stage"):
            case.growth_stage = corrections["growth_stage"]
        correction_days = self._coerce_days_to_harvest(corrections.get("days_to_harvest"))
        if correction_days is not None:
            case.days_to_harvest = correction_days
        if corrections.get("recent_weather"):
            case.recent_weather = corrections["recent_weather"]
        if corrections.get("location_text"):
            current = dict(case.structured_data or {})
            weather = dict(current.get("weather_observation") or {})
            weather["location"] = corrections["location_text"]
            weather["location_source"] = "llm_correction"
            current["weather_observation"] = weather
            case.structured_data = current

        if raw.get("growth_stage") and not case.growth_stage:
            case.growth_stage = raw["growth_stage"]
        if raw.get("recent_weather") and not case.recent_weather:
            case.recent_weather = raw["recent_weather"]
        raw_days = self._coerce_days_to_harvest(raw.get("days_to_harvest"))
        if raw_days is not None and case.days_to_harvest is None:
            case.days_to_harvest = raw_days
        if raw.get("environment") and not case.environment:
            case.environment = raw["environment"]
        if raw.get("recent_pesticide_use") and not case.recent_pesticide_use:
            case.recent_pesticide_use = raw["recent_pesticide_use"]
        if raw.get("recent_fertilizer_use") and not case.recent_fertilizer_use:
            case.recent_fertilizer_use = raw["recent_fertilizer_use"]

    def _coerce_days_to_harvest(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            match = re.search(r"\d{1,3}", value)
            if match:
                return int(match.group(0))
        return None

    def _build_decision_trace(self, context: AgentDecisionContext, decision) -> dict:
        return {
            "observe": {
                "input": {
                    "latest_user_message": context.latest_user_message,
                    "case_status": context.case_status.value,
                    "active_followup": context.active_followup,
                    "history_summary": context.history_summary,
                },
                "output": {
                    "structured_symptoms": context.structured_symptoms.model_dump(mode="json"),
                    "vision_observation": context.vision_observation,
                    "semantic_observation": context.semantic_observation,
                    "weather_observation": context.weather_observation,
                    "date_observation": context.date_observation,
                },
                "case_status": context.case_status.value,
                "latest_user_message": context.latest_user_message,
                "missing_fields": context.structured_symptoms.missing_fields,
                "affected_parts": context.structured_symptoms.affected_parts,
                "symptoms": context.structured_symptoms.symptoms,
                "vision_status": (context.vision_observation or {}).get("status"),
                "vision_confidence": (context.vision_observation or {}).get("confidence"),
                "semantic_status": (context.semantic_observation or {}).get("status"),
                "semantic_intent": (context.semantic_observation or {}).get("user_intent"),
                "semantic_followup_trend": (context.semantic_observation or {}).get("followup_trend"),
                "weather_status": bool(context.weather_observation),
                "weather_risk_signals": (context.weather_observation or {}).get("risk_signals", []),
                "today": (context.date_observation or {}).get("today"),
                "active_followup": bool(context.active_followup),
            },
            "decide": {
                "input": {
                    "available_actions": [action.value for action in context.available_actions],
                    "structured_symptoms": context.structured_symptoms.model_dump(mode="json"),
                    "vision_observation": context.vision_observation,
                    "semantic_observation": context.semantic_observation,
                    "weather_observation": context.weather_observation,
                    "date_observation": context.date_observation,
                    "active_followup": context.active_followup,
                },
                "output": decision.model_dump(mode="json"),
                "source": decision.decision_source,
                "next_action": decision.next_action.value,
                "requested_state": decision.requested_state.value if decision.requested_state else None,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "fallback_reason": decision.fallback_reason,
                "observations_used": decision.observations_used,
                "user_intent": decision.user_intent,
                "response_focus": decision.response_focus,
            },
            "act": {
                "input": {
                    "next_action": decision.next_action.value,
                    "tool_plan": decision.tool_plan,
                    "questions": decision.questions,
                },
                "output": {
                    "planned_tools": decision.tool_plan,
                    "response_focus": decision.response_focus,
                },
                "planned_tools": decision.tool_plan,
                "questions": decision.questions,
            },
            "guard": {
                "input": {
                    "requested_state": decision.requested_state.value if decision.requested_state else None,
                    "confidence": decision.confidence,
                    "problem_category": decision.problem_category,
                    "severity_label": decision.severity_label,
                },
                "output": {
                    "guardrails": decision.guardrails,
                    "state_machine_required": True,
                    "safety_check_required": decision.next_action == AgentAction.DIAGNOSE_AND_PLAN,
                },
                "guardrails": decision.guardrails,
            },
            "memory": {
                "input": {
                    "case_id_context": context.case_status.value,
                    "next_action": decision.next_action.value,
                },
                "output": {
                    "will_write_events": self._events_for_action(decision.next_action),
                },
                "will_write_events": self._events_for_action(decision.next_action),
            },
        }

    def _events_for_action(self, action: AgentAction) -> list[str]:
        common = [
            EventType.AGENT_DECISION.value,
            EventType.TOOL_CALLED.value,
            EventType.AGENT_RESPONSE.value,
        ]
        if action == AgentAction.ASK_MORE_INFO:
            return [*common, EventType.QUESTIONS_ASKED.value, EventType.STATE_CHANGED.value]
        if action == AgentAction.DIAGNOSE_AND_PLAN:
            return [
                *common,
                EventType.DIAGNOSIS_GENERATED.value,
                EventType.SAFETY_CHECKED.value,
                EventType.PLAN_GENERATED.value,
                EventType.FOLLOWUP_CREATED.value,
                EventType.STATE_CHANGED.value,
            ]
        if action == AgentAction.COMPARE_FOLLOWUP:
            return [
                *common,
                EventType.FOLLOWUP_SUBMITTED.value,
                EventType.FOLLOWUP_COMPARED.value,
                EventType.STATE_CHANGED.value,
            ]
        if action == AgentAction.ESCALATE:
            return [*common, EventType.ESCALATED.value, EventType.STATE_CHANGED.value]
        if action == AgentAction.CLOSE_CASE:
            return [*common, EventType.CASE_CLOSED.value]
        return common

    def _fuse_observations(
        self,
        structured: StructuredSymptoms,
        vision_observation: dict | None,
        case,
    ) -> StructuredSymptoms:
        fused = structured.model_copy(deep=True)
        existing_structured = case.structured_data or {}
        if case.affected_parts:
            fused.affected_parts = self._unique([*fused.affected_parts, *case.affected_parts])
        if existing_structured.get("symptoms"):
            fused.symptoms = self._unique([*fused.symptoms, *existing_structured.get("symptoms", [])])
        if existing_structured.get("possible_categories"):
            fused.possible_categories = self._unique(
                [*fused.possible_categories, *existing_structured.get("possible_categories", [])]
            )
        if existing_structured.get("raw"):
            for key, value in existing_structured.get("raw", {}).items():
                if key not in fused.raw or fused.raw.get(key) in (None, [], ""):
                    fused.raw[key] = value
        if case.suspected_problem:
            fused.raw.setdefault("case_suspected_problem", case.suspected_problem)
            fused.raw["mentioned_problems"] = self._unique(
                [*fused.raw.get("mentioned_problems", []), case.suspected_problem]
            )
        if case.growth_stage:
            fused.raw.setdefault("growth_stage", case.growth_stage)
        if case.days_to_harvest is not None:
            fused.raw.setdefault("days_to_harvest", case.days_to_harvest)
        if case.recent_weather:
            fused.raw.setdefault("recent_weather", case.recent_weather)
        if case.environment:
            fused.raw.setdefault("environment", case.environment)
        if case.recent_pesticide_use:
            fused.raw.setdefault("recent_pesticide_use", case.recent_pesticide_use)
        if case.recent_fertilizer_use:
            fused.raw.setdefault("recent_fertilizer_use", case.recent_fertilizer_use)
        if structured.raw.get("mentioned_problems"):
            fused.raw["mentioned_problems"] = self._unique(
                [
                    *fused.raw.get("mentioned_problems", []),
                    *structured.raw.get("mentioned_problems", []),
                ]
            )
        if (case.structured_data or {}).get("raw", {}).get("mentioned_problems"):
            fused.raw["mentioned_problems"] = self._unique(
                [
                    *fused.raw.get("mentioned_problems", []),
                    *(case.structured_data or {}).get("raw", {}).get("mentioned_problems", []),
                ]
            )

        if vision_observation and vision_observation.get("is_configured"):
            fused.raw["vision_possible_problems"] = self._unique(
                [
                    *fused.raw.get("vision_possible_problems", []),
                    *vision_observation.get("possible_problems", []),
                ]
            )
            fused.affected_parts = self._unique(
                [*fused.affected_parts, *vision_observation.get("observed_parts", [])]
            )
            fused.symptoms = self._unique(
                [*fused.symptoms, *vision_observation.get("visual_symptoms", [])]
            )
            fused.possible_categories = self._unique(
                [
                    *fused.possible_categories,
                    *self._infer_categories(vision_observation.get("possible_problems", [])),
                ]
            )
            if vision_observation.get("severity_signals") and not fused.severity:
                fused.severity = "需关注"
            if vision_observation.get("growth_stage_hint") and not fused.raw.get("growth_stage"):
                fused.raw["growth_stage"] = vision_observation["growth_stage_hint"]
            if vision_observation.get("harvest_hint") and not fused.raw.get("harvest_hint"):
                fused.raw["harvest_hint"] = vision_observation["harvest_hint"]

        fused.missing_fields = self._remaining_missing_fields(fused)
        return fused

    def _build_multimodal_observation(
        self,
        text_structured: StructuredSymptoms,
        fused_structured: StructuredSymptoms,
        vision_observation: dict,
    ) -> dict:
        return {
            "text": {
                "affected_parts": text_structured.affected_parts,
                "symptoms": text_structured.symptoms,
                "missing_fields": text_structured.missing_fields,
            },
            "vision": {
                "observed_parts": vision_observation.get("observed_parts", []),
                "visual_symptoms": vision_observation.get("visual_symptoms", []),
                "possible_problems": vision_observation.get("possible_problems", []),
                "severity_signals": vision_observation.get("severity_signals", []),
                "confidence": vision_observation.get("confidence", "low"),
                "uncertainties": vision_observation.get("uncertainties", []),
            },
            "fused": {
                "affected_parts": fused_structured.affected_parts,
                "symptoms": fused_structured.symptoms,
                "possible_categories": fused_structured.possible_categories,
                "missing_fields": fused_structured.missing_fields,
            },
        }

    def _remaining_missing_fields(self, structured: StructuredSymptoms) -> list[str]:
        missing = []
        if not structured.affected_parts:
            missing.append("发生部位")
        if not structured.raw.get("growth_stage"):
            missing.append("生长阶段")
        if structured.raw.get("days_to_harvest") is None:
            missing.append("距离采收时间")
        if not (
            structured.raw.get("recent_pesticide_use")
            or structured.raw.get("recent_fertilizer_use")
        ):
            missing.append("近期施肥或用药")
        return missing

    def _infer_categories(self, possible_problems: list[str]) -> list[str]:
        categories = []
        text = " ".join(possible_problems)
        if any(word in text for word in ["虫", "粉虱", "蚜", "螨"]):
            categories.append("虫害")
        if any(word in text for word in ["病", "疫", "霉", "斑"]):
            categories.append("病害")
        if any(word in text for word in ["缺", "肥", "灼", "裂", "生理"]):
            categories.append("生理性问题")
        return categories

    def _unique(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))

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

    def _trend_from_semantic(self, semantic: dict) -> FollowupTrend:
        trend = semantic.get("followup_trend")
        if trend:
            return FollowupTrend(trend)
        raise AgentDecisionError("语义观察没有返回可用的复查趋势。")

    def _trend_from_decision_or_semantic(self, decision, semantic: dict) -> FollowupTrend:
        if decision is not None and getattr(decision, "followup_trend", None):
            return FollowupTrend(decision.followup_trend)
        return self._trend_from_semantic(semantic)

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
