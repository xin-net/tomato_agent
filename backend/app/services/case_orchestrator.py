from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.agents.decision_engine import AgentDecisionEngine
from app.domain.enums import AgentAction, CaseStatus, EventType, FollowupTrend
from app.domain.safety import SafetyChecker, SafetyContext
from app.domain.state_machine import StateMachine
from app.repositories.case_repository import CaseRepository
from app.repositories.event_repository import EventRepository
from app.repositories.followup_repository import FollowupRepository
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
from app.tools.diagnosis_tool import DiagnosisTool, PlanTool
from app.tools.followup_compare_tool import FollowupCompareTool
from app.tools.knowledge_search_tool import KnowledgeSearchTool
from app.tools.symptom_extraction_tool import SymptomExtractionTool


class CaseOrchestrator:
    def __init__(self, db: Session):
        self.db = db
        self.cases = CaseRepository(db)
        self.events = EventRepository(db)
        self.followups = FollowupRepository(db)
        self.extractor = SymptomExtractionTool()
        self.decision_engine = AgentDecisionEngine()
        self.knowledge = KnowledgeSearchTool()
        self.diagnosis_tool = DiagnosisTool()
        self.plan_tool = PlanTool()
        self.followup_compare = FollowupCompareTool()
        self.state_machine = StateMachine()
        self.safety = SafetyChecker()

    def create_case(self, data: CreateCaseInput) -> CaseResponse:
        title = self._make_title(data.symptoms)
        case = self.cases.create(data, title=title)
        self.events.append(case.id, EventType.CASE_CREATED, user_input=data.symptoms)
        self.events.append(case.id, EventType.USER_MESSAGE, user_input=data.symptoms)

        response = self._handle_message(case, data.symptoms)
        self.db.commit()
        return response

    def reply_to_case(self, case_id: int, data: ReplyInput) -> CaseResponse:
        case = self._require_case(case_id)
        case.symptoms = f"{case.symptoms}\n{data.message}".strip()
        self.events.append(case.id, EventType.USER_MESSAGE, user_input=data.message)
        response = self._handle_message(case, data.message)
        self.db.commit()
        return response

    def submit_followup(self, case_id: int, data: FollowupInput) -> CaseResponse:
        case = self._require_case(case_id)
        active = self.followups.active_for_case(case.id)
        self.events.append(case.id, EventType.FOLLOWUP_SUBMITTED, user_input=data.description)

        trend, evidence = self.followup_compare.compare(data)
        requested_state = self._state_for_trend(trend)
        transition = self.state_machine.apply(case, requested_state, "复查趋势判断")
        if not transition.allowed:
            requested_state = CaseStatus.ESCALATED
            self.state_machine.apply(case, requested_state, transition.reason)

        if active:
            self.followups.submit(active, data.description, trend.value)

        system_output = {"trend": trend.value, "evidence": evidence}
        self.events.append(case.id, EventType.FOLLOWUP_COMPARED, system_output=system_output)
        self.events.append(
            case.id,
            EventType.STATE_CHANGED,
            system_output={"status": case.status, "reason": "复查趋势判断"},
        )

        message = self._followup_message(trend)
        self.db.commit()
        return CaseResponse(
            case_id=case.id,
            status=CaseStatus(case.status),
            response_type="followup_result",
            message=message,
            trend=trend,
            followup=FollowupRead.model_validate(active) if active else None,
        )

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
        self.db.commit()
        return CaseResponse(
            case_id=case.id,
            status=CaseStatus(case.status),
            response_type="closed",
            message=f"病例已结案。{summary}",
        )

    def _handle_message(self, case, message: str) -> CaseResponse:
        structured = self.extractor.extract(message)
        case.structured_data = structured.model_dump()
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
            return self.submit_followup(case.id, followup_input)
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
            case.followup_date = due_date
            self.events.append(
                case.id,
                EventType.FOLLOWUP_CREATED,
                system_output={"followup_id": followup.id, "due_date": due_date.isoformat()},
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

    def _state_for_trend(self, trend: FollowupTrend) -> CaseStatus:
        if trend == FollowupTrend.IMPROVING:
            return CaseStatus.IMPROVING
        if trend == FollowupTrend.WORSENING:
            return CaseStatus.ESCALATED
        if trend == FollowupTrend.NEEDS_HUMAN_CONFIRMATION:
            return CaseStatus.ESCALATED
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
