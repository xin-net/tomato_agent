import json

from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.domain.enums import AgentAction, CaseStatus
from app.schemas.agent import AgentDecision, AgentDecisionContext
from app.tools.llm_adapter import OpenAIAdapter


class AgentDecisionError(RuntimeError):
    pass


class LLMDecisionPayload(BaseModel):
    next_action: AgentAction
    reason: str
    confidence: str = "medium"
    requested_state: CaseStatus | None = None
    questions: list[str] = Field(default_factory=list)
    observations_used: list[str] = Field(default_factory=list)
    tool_plan: list[str] = Field(default_factory=list)
    user_intent: str = "initial_diagnosis"
    response_focus: list[str] = Field(default_factory=list)
    information_sufficient: bool | None = None
    problem_category: str | None = None
    likely_causes: list[str] = Field(default_factory=list)
    diagnosis_evidence: list[str] = Field(default_factory=list)
    confidence_label: str | None = None
    severity_label: str | None = None
    immediate_actions: list[str] = Field(default_factory=list)
    observation_points: list[str] = Field(default_factory=list)
    escalation_conditions: list[str] = Field(default_factory=list)
    followup_after_days: int | None = None
    chemical_safety_note: str | None = None
    harvest_safety_note: str | None = None
    plain_summary: str | None = None


class AgentDecisionEngine:
    def __init__(self, llm: OpenAIAdapter | None = None):
        self.llm = llm or OpenAIAdapter()

    def decide(self, context: AgentDecisionContext) -> AgentDecision:
        baseline = self._ensure_available_action(self._rule_decide(context), context)
        settings = get_settings()
        if settings.agent_decision_mode.lower() != "llm":
            return baseline

        if context.case_status == CaseStatus.CLOSED:
            baseline.decision_source = "rule_guardrail"
            baseline.guardrails = self._guardrails_for(context)
            return baseline

        result = self.llm.complete(self._build_prompt(context, baseline))
        if not result.is_configured:
            raise AgentDecisionError(f"Agent 决策模型不可用：{result.content}")

        try:
            payload = self._parse_llm_payload(result.content)
            decision = AgentDecision(
                next_action=payload.next_action,
                reason=payload.reason,
                confidence=payload.confidence,
                requested_state=payload.requested_state,
                questions=payload.questions,
                decision_source=f"llm:{result.provider}:{result.model}",
                observations_used=payload.observations_used,
                tool_plan=payload.tool_plan,
                user_intent=payload.user_intent,
                response_focus=payload.response_focus,
                information_sufficient=payload.information_sufficient,
                problem_category=payload.problem_category,
                likely_causes=payload.likely_causes,
                diagnosis_evidence=payload.diagnosis_evidence,
                confidence_label=payload.confidence_label,
                severity_label=payload.severity_label,
                immediate_actions=payload.immediate_actions,
                observation_points=payload.observation_points,
                escalation_conditions=payload.escalation_conditions,
                followup_after_days=payload.followup_after_days,
                chemical_safety_note=payload.chemical_safety_note,
                harvest_safety_note=payload.harvest_safety_note,
                plain_summary=payload.plain_summary,
                guardrails=self._guardrails_for(context),
            )
            return self._sanitize_llm_decision(decision, baseline, context)
        except (ValueError, ValidationError) as exc:
            raise AgentDecisionError(f"Agent 决策输出不可用：{exc}") from exc

    def _rule_decide(self, context: AgentDecisionContext) -> AgentDecision:
        if context.case_status == CaseStatus.CLOSED:
            return AgentDecision(
                next_action=AgentAction.ESCALATE,
                reason="当前病例已结案，不能直接追加普通处置流程。",
                requested_state=CaseStatus.ESCALATED,
                confidence="medium",
                decision_source="rule",
                observations_used=["case_status=CLOSED"],
                tool_plan=["StateMachine"],
                user_intent="closed_case_message",
                response_focus=["解释病例已关闭，建议如有新异常重新创建病例"],
                guardrails=self._guardrails_for(context),
            )

        if self._is_followup_change_message(context):
            semantic = context.semantic_observation or {}
            return AgentDecision(
                next_action=AgentAction.COMPARE_FOLLOWUP,
                reason="语义观察显示用户正在描述本病例后续变化，需要比较复查趋势并调整方案。",
                requested_state=CaseStatus.FOLLOWUP_REVIEW,
                confidence="high",
                decision_source="semantic_guardrail" if semantic.get("is_configured") else "rule",
                observations_used=self._observation_summary(context),
                tool_plan=["SemanticObservationTool", "DateTool", "StateMachine", "CalendarReminderTool", "EventMemory"],
                user_intent="followup_change_report",
                response_focus=["判断变化趋势", "根据好转或加重调整处置", "调整复查和提醒"],
                information_sufficient=True,
                problem_category=semantic.get("possible_categories", [None])[0]
                if semantic.get("possible_categories")
                else None,
                likely_causes=semantic.get("mentioned_problems", []),
                diagnosis_evidence=semantic.get("followup_evidence", []),
                confidence_label=semantic.get("confidence"),
                severity_label=semantic.get("severity"),
                plain_summary="用户正在描述本病例后续变化，需要比较趋势并调整处置和复查。",
                guardrails=self._guardrails_for(context),
            )

        return AgentDecision(
            next_action=AgentAction.DIAGNOSE_AND_PLAN,
            reason="等待 LLM 决策；此 baseline 只用于动作白名单和安全边界。",
            requested_state=CaseStatus.FOLLOWUP_PENDING,
            confidence="low",
            decision_source="baseline",
            observations_used=self._observation_summary(context),
            tool_plan=["SafetyChecker", "CalendarReminderTool", "ResponseComposer"],
            user_intent="unknown",
            response_focus=["由 LLM 决定本轮回答焦点"],
            guardrails=self._guardrails_for(context),
        )

    def _build_prompt(self, context: AgentDecisionContext, baseline: AgentDecision) -> str:
        allowed_actions = [action.value for action in context.available_actions]
        compact_context = {
            "case_status": context.case_status.value,
            "latest_user_message": context.latest_user_message,
            "structured_symptoms": context.structured_symptoms.model_dump(),
            "vision_observation": context.vision_observation,
            "multimodal_observation": context.multimodal_observation,
            "semantic_observation": context.semantic_observation,
            "weather_observation": context.weather_observation,
            "date_observation": context.date_observation,
            "active_followup": context.active_followup,
            "history_summary": context.history_summary,
            "available_actions": allowed_actions,
            "baseline_rule_decision": baseline.model_dump(mode="json"),
        }
        return (
            "你是 Tomato Case Agent 的决策核心。"
            "你的目标是把当前番茄异常病例推进到安全、可执行、可复查、可记录的下一步。"
            "你负责综合观察并形成本轮判断：信息是否足够、疑似类别、可能原因、严重程度、风险点、下一步动作、工具计划和回复焦点。"
            "你不能直接修改数据库，不能绕过状态机、安全检查、工具权限和输出安全边界。"
            "请输出严格 JSON，不要输出 Markdown。"
            "动作只能来自 available_actions。"
            "如果信息不足以给出处置建议，选择 ASK_MORE_INFO，并给出具体追问。"
            "如果信息足以形成保守判断并安排处置/复查，选择 DIAGNOSE_AND_PLAN。"
            "active_followup 只表示系统已有复查计划，不表示用户当前消息一定是复查。"
            "只有 semantic_observation 显示用户本轮确实是在描述后续变化时，才选择 COMPARE_FOLLOWUP。"
            "如果用户是在补充信息、提出猜测、纠正事实、询问能否用药或下一步怎么做，应继续综合判断并选择 DIAGNOSE_AND_PLAN 或 ASK_MORE_INFO。"
            "地点来自 LocationTool，天气来自 WeatherTool，图片观察来自 VisionTool，语义观察来自 SemanticObservationTool；你需要综合它们。"
            "不要给具体农药名称、剂量、兑水比例、施药频次或混配处方。涉及用药时只给安全边界和咨询当地登记标签/农技人员的建议。"
            "不要选择 CLOSE_CASE，除非用户明确要求停止跟踪该问题。"
            "返回字段：next_action, reason, confidence, requested_state, questions, observations_used, tool_plan, user_intent, response_focus,"
            "information_sufficient, problem_category, likely_causes, diagnosis_evidence, confidence_label, severity_label,"
            "immediate_actions, observation_points, escalation_conditions, followup_after_days, chemical_safety_note, harvest_safety_note, plain_summary。"
            f"\n上下文 JSON：{json.dumps(compact_context, ensure_ascii=False)}"
        )

    def _parse_llm_payload(self, content: str) -> LLMDecisionPayload:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("未找到 JSON 对象")
        return LLMDecisionPayload.model_validate(json.loads(text[start : end + 1]))

    def _sanitize_llm_decision(
        self,
        decision: AgentDecision,
        baseline: AgentDecision,
        context: AgentDecisionContext,
    ) -> AgentDecision:
        if decision.next_action not in context.available_actions:
            raise AgentDecisionError(f"Agent 选择了不可用动作：{decision.next_action.value}")

        if decision.next_action == AgentAction.ASK_MORE_INFO and not decision.questions:
            raise AgentDecisionError("Agent 选择追问信息但没有给出 questions。")

        if self._is_followup_change_message(context):
            decision.next_action = AgentAction.COMPARE_FOLLOWUP
            decision.requested_state = CaseStatus.FOLLOWUP_REVIEW
            decision.user_intent = "followup_change_report"
            decision.response_focus = decision.response_focus or ["判断变化趋势", "根据变化调整方案"]

        if decision.next_action == AgentAction.ASK_MORE_INFO:
            decision.requested_state = CaseStatus.NEED_MORE_INFO
        elif decision.next_action == AgentAction.DIAGNOSE_AND_PLAN:
            decision.requested_state = CaseStatus.FOLLOWUP_PENDING
        elif decision.next_action == AgentAction.COMPARE_FOLLOWUP:
            decision.requested_state = CaseStatus.FOLLOWUP_REVIEW
        elif decision.next_action == AgentAction.ESCALATE:
            decision.requested_state = CaseStatus.ESCALATED

        if not decision.observations_used:
            decision.observations_used = self._observation_summary(context)
        if not decision.tool_plan:
            decision.tool_plan = baseline.tool_plan
        if not decision.response_focus:
            decision.response_focus = baseline.response_focus
        return self._ensure_available_action(decision, context)

    def _ensure_available_action(
        self,
        decision: AgentDecision,
        context: AgentDecisionContext,
    ) -> AgentDecision:
        if decision.next_action in context.available_actions:
            return decision

        fallback_reason = (
            decision.fallback_reason
            or f"决策动作 {decision.next_action.value} 不在当前可用动作白名单中，已回退到保守可用动作。"
        )
        if AgentAction.ASK_MORE_INFO in context.available_actions:
            return AgentDecision(
                next_action=AgentAction.ASK_MORE_INFO,
                reason="当前动作受状态/权限约束，先补充信息以避免越权推进。",
                requested_state=CaseStatus.NEED_MORE_INFO,
                questions=decision.questions
                or [
                    "请补充异常发生部位、症状形态、生长阶段、距离采收时间和近期用药/施肥情况。"
                ],
                confidence="medium",
                decision_source=decision.decision_source,
                observations_used=decision.observations_used or self._observation_summary(context),
                tool_plan=["Questions", "StateMachine", "EventMemory"],
                user_intent=decision.user_intent,
                response_focus=decision.response_focus,
                guardrails=decision.guardrails or self._guardrails_for(context),
                fallback_reason=fallback_reason,
            )
        if AgentAction.ESCALATE in context.available_actions:
            return AgentDecision(
                next_action=AgentAction.ESCALATE,
                reason="当前没有可安全自动执行的动作，升级为人工确认。",
                requested_state=CaseStatus.ESCALATED,
                confidence="medium",
                decision_source=decision.decision_source,
                observations_used=decision.observations_used or self._observation_summary(context),
                tool_plan=["StateMachine", "EventMemory"],
                user_intent=decision.user_intent,
                response_focus=decision.response_focus,
                guardrails=decision.guardrails or self._guardrails_for(context),
                fallback_reason=fallback_reason,
            )

        first_action = context.available_actions[0] if context.available_actions else AgentAction.ESCALATE
        decision.next_action = first_action
        decision.requested_state = self._state_for_action(first_action)
        decision.fallback_reason = fallback_reason
        decision.guardrails = decision.guardrails or self._guardrails_for(context)
        return decision

    def _state_for_action(self, action: AgentAction) -> CaseStatus:
        if action == AgentAction.ASK_MORE_INFO:
            return CaseStatus.NEED_MORE_INFO
        if action == AgentAction.DIAGNOSE_AND_PLAN:
            return CaseStatus.FOLLOWUP_PENDING
        if action == AgentAction.COMPARE_FOLLOWUP:
            return CaseStatus.FOLLOWUP_REVIEW
        if action == AgentAction.CLOSE_CASE:
            return CaseStatus.CLOSED
        return CaseStatus.ESCALATED

    def _effective_missing_fields(self, context: AgentDecisionContext) -> set[str]:
        missing = set(context.structured_symptoms.missing_fields)
        if context.vision_observation and context.vision_observation.get("is_configured"):
            if context.vision_observation.get("observed_parts"):
                missing.discard("发生部位")
            if context.vision_observation.get("visual_symptoms"):
                missing.discard("发生部位")
        return missing

    def _has_high_confidence_vision(self, context: AgentDecisionContext) -> bool:
        return bool(
            context.vision_observation
            and context.vision_observation.get("is_configured")
            and context.vision_observation.get("confidence") in {"medium", "high"}
            and (
                context.vision_observation.get("observed_parts")
                or context.vision_observation.get("visual_symptoms")
            )
        )

    def _observation_summary(self, context: AgentDecisionContext) -> list[str]:
        summary = [
            f"病例状态：{context.case_status.value}",
            f"缺失字段：{', '.join(context.structured_symptoms.missing_fields) or '无'}",
        ]
        if context.structured_symptoms.affected_parts:
            summary.append(f"文本/融合部位：{', '.join(context.structured_symptoms.affected_parts[:4])}")
        if context.structured_symptoms.symptoms:
            summary.append(f"文本/融合症状：{', '.join(context.structured_symptoms.symptoms[:4])}")
        if context.vision_observation:
            summary.append(
                "视觉观察："
                + ", ".join(
                    (
                        context.vision_observation.get("observed_parts", [])[:3]
                        + context.vision_observation.get("visual_symptoms", [])[:3]
                    )
                    or [context.vision_observation.get("status", "unknown")]
                )
            )
        if context.active_followup:
            summary.append("存在待复查任务")
        if context.weather_observation:
            weather_parts = []
            if context.weather_observation.get("weather"):
                weather_parts.append(str(context.weather_observation.get("weather")))
            if context.weather_observation.get("current_temperature_c") is not None:
                weather_parts.append(f"{context.weather_observation.get('current_temperature_c')}℃")
            if context.weather_observation.get("current_relative_humidity") is not None:
                weather_parts.append(f"湿度{context.weather_observation.get('current_relative_humidity')}%")
            if weather_parts:
                summary.append("天气观察：" + "，".join(weather_parts[:3]))
        if context.date_observation:
            summary.append(f"当前日期：{context.date_observation.get('today')}")
        return summary

    def _guardrails_for(self, context: AgentDecisionContext) -> list[str]:
        return [
            "动作必须来自 AgentAction 白名单",
            "状态变更必须通过 StateMachine",
            "处置建议必须经过 SafetyChecker",
            "工具输出必须写入 Case/Event Memory",
            f"当前可选动作：{', '.join(action.value for action in context.available_actions)}",
        ]

    def _is_followup_change_message(self, context: AgentDecisionContext) -> bool:
        if not context.active_followup:
            return False
        semantic = context.semantic_observation or {}
        return bool(semantic.get("is_configured") and semantic.get("is_followup_report"))
