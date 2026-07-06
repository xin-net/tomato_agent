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
                guardrails=self._guardrails_for(context),
            )
            return self._sanitize_llm_decision(decision, baseline, context)
        except (ValueError, ValidationError) as exc:
            raise AgentDecisionError(f"Agent 决策输出不可用：{exc}") from exc

    def _rule_decide(self, context: AgentDecisionContext) -> AgentDecision:
        intent, focus = self._infer_turn_focus(context)
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

        missing = self._effective_missing_fields(context)
        high_confidence_vision = self._has_high_confidence_vision(context)
        if self._is_followup_change_message(context):
            return AgentDecision(
                next_action=AgentAction.COMPARE_FOLLOWUP,
                reason="用户正在描述本病例后续变化，需要比较复查趋势并调整方案。",
                requested_state=CaseStatus.FOLLOWUP_REVIEW,
                confidence="high",
                decision_source="rule",
                observations_used=self._observation_summary(context),
                tool_plan=["DateTool", "FollowupCompareTool", "StateMachine", "CalendarReminderTool", "EventMemory"],
                user_intent="followup_change_report",
                response_focus=["判断变化趋势", "如果虫量变多则升级处理", "调整复查和提醒"],
                guardrails=self._guardrails_for(context),
            )

        if {"发生部位", "生长阶段"}.issubset(missing) or (
            len(missing) >= 3 and not high_confidence_vision
        ):
            questions = [
                "异常主要出现在老叶、新叶、叶背、茎、花还是果实？",
                "斑点是什么颜色和形态？是否有同心轮纹或霉层？",
                "番茄目前处于苗期、开花期、结果期还是采收期？",
                "最近是否施肥、喷药，距离预计采收还有几天？",
            ]
            if high_confidence_vision:
                questions = context.vision_observation.get("suggested_questions") or questions[2:]
            return AgentDecision(
                next_action=AgentAction.ASK_MORE_INFO,
                reason="缺少发生部位、生长阶段、采收时间或近期用药等关键信息。",
                requested_state=CaseStatus.NEED_MORE_INFO,
                questions=questions,
                confidence="high",
                decision_source="rule",
                observations_used=self._observation_summary(context),
                tool_plan=["Questions", "StateMachine", "EventMemory"],
                user_intent=intent,
                response_focus=focus or ["追问缺失信息", "暂不建议直接用药"],
                guardrails=self._guardrails_for(context),
            )

        return AgentDecision(
            next_action=AgentAction.DIAGNOSE_AND_PLAN,
            reason="当前信息足以形成保守的初步判断并创建复查计划。",
            requested_state=CaseStatus.FOLLOWUP_PENDING,
            confidence="medium",
            decision_source="rule",
            observations_used=self._observation_summary(context),
            tool_plan=self._tool_plan_for_intent(intent),
            user_intent=intent,
            response_focus=focus,
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
            "weather_observation": context.weather_observation,
            "date_observation": context.date_observation,
            "active_followup": context.active_followup,
            "history_summary": context.history_summary,
            "available_actions": allowed_actions,
            "baseline_rule_decision": baseline.model_dump(mode="json"),
        }
        return (
            "你是番茄病虫害处置闭环系统里的 Agent 决策器。"
            "你只能选择下一步动作，不能直接生成最终诊断、不能修改数据库、不能绕过状态机和安全检查。"
            "请基于目标、病例状态、用户输入、视觉观察和缺失字段，输出严格 JSON，不要输出 Markdown。"
            "动作只能来自 available_actions。"
            "当信息不足时选择 ASK_MORE_INFO，并给出具体追问。"
            "当信息足以保守判断时选择 DIAGNOSE_AND_PLAN。"
            "active_followup 只表示系统已有复查计划，不表示用户当前消息一定是复查。"
            "只有当用户明确在描述处理后或一段时间后的变化时，才选择 COMPARE_FOLLOWUP，"
            "例如：复查、按你说处理后、剪掉病叶后、三天后、没有新增、变多、扩散、好转、恶化、稳定。"
            "如果用户只是补充图片、补充症状、提出猜测、问“是不是白粉虱/早疫病”、纠正诊断或继续询问怎么办，"
            "应选择 DIAGNOSE_AND_PLAN 或 ASK_MORE_INFO，而不是 COMPARE_FOLLOWUP。"
            "你还必须判断本轮用户意图 user_intent 和回答焦点 response_focus。"
            "如果用户追问“能不能用药、能不能打药、采收前能否用药”，user_intent 应为 chemical_safety_question，"
            "response_focus 应聚焦采收安全、是否适合用药、安全边界和下一步观察，不要重复完整诊断。"
            "如果用户追问“用什么药、推荐药名、剂量、兑水、频次”，user_intent 应为 pesticide_detail_question，"
            "response_focus 应说明本系统不直接给具体药名/剂量/兑水/频次，并建议核对当地登记标签和农技人员。"
            "如果用户只是问后续怎么做，聚焦处置方案和复查；如果用户纠正诊断，聚焦重新评估和方案调整。"
            "不要选择 CLOSE_CASE，除非用户明确要求停止跟踪该问题。"
            "返回字段：next_action, reason, confidence, requested_state, questions, observations_used, tool_plan, user_intent, response_focus。"
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

        missing = self._effective_missing_fields(context)
        high_confidence_vision = self._has_high_confidence_vision(context)
        if decision.next_action == AgentAction.DIAGNOSE_AND_PLAN and len(missing) >= 3 and not high_confidence_vision:
            raise AgentDecisionError("Agent 尝试在关键信息不足时直接诊断。")

        if decision.next_action == AgentAction.ASK_MORE_INFO and not decision.questions:
            decision.questions = baseline.questions

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
            decision.tool_plan = self._tool_plan_for_intent(decision.user_intent) or baseline.tool_plan
        if not decision.response_focus:
            decision.response_focus = baseline.response_focus or self._infer_turn_focus(context)[1]
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
            signals = context.weather_observation.get("risk_signals", [])
            if signals:
                summary.append("天气观察：" + "；".join(signals[:2]))
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

    def _infer_turn_focus(self, context: AgentDecisionContext) -> tuple[str, list[str]]:
        text = context.latest_user_message or ""
        if any(word in text for word in ["用什么药", "什么药", "药名", "剂量", "兑水", "频次", "喷几次"]):
            return (
                "pesticide_detail_question",
                [
                    "回答用户对具体药剂/剂量的追问",
                    "明确不提供具体药名、剂量、兑水比例或施药频次",
                    "结合采收时间提醒核对登记标签和安全间隔期",
                    "给出可执行的非化学处理和观察重点",
                ],
            )
        if any(word in text for word in ["能不能用药", "能用药", "可以用药", "打药", "喷药", "收获"]):
            return (
                "chemical_safety_question",
                [
                    "回答现在是否适合用药",
                    "结合距离采收时间说明安全边界",
                    "优先给出非化学处理",
                    "说明需要核对当地登记标签和安全间隔期",
                ],
            )
        if any(word in text for word in ["怎么办", "怎么处理", "怎么解决", "建议怎么", "下一步"]):
            return (
                "handling_plan_question",
                ["聚焦下一步处理", "说明观察重点", "说明何时复查或调整方案"],
            )
        if any(word in text for word in ["是不是", "应该是", "听说", "像不像"]):
            return (
                "diagnosis_correction_or_hypothesis",
                ["回应用户提出的候选问题", "重新核对诊断", "如方案变化则说明调整点"],
            )
        if self._is_followup_change_message(context):
            return (
                "followup_change_report",
                ["判断变化趋势", "如果虫量或病斑增加则升级处理", "调整复查和提醒"],
            )
        if context.active_followup and context.active_followup.get("is_due"):
            return (
                "due_followup_context",
                ["提醒复查已到期或临近", "请用户描述变化", "根据变化调整方案"],
            )
        return (
            "initial_diagnosis",
            ["判断信息是否足够", "说明疑似类型和严重程度", "给出处置和复查计划"],
        )

    def _is_followup_change_message(self, context: AgentDecisionContext) -> bool:
        if not context.active_followup:
            return False
        text = context.latest_user_message or ""
        change_words = [
            "更多",
            "变多",
            "增加",
            "新增",
            "扩散",
            "扩大",
            "严重",
            "更严重",
            "好转",
            "稳定",
            "没有新增",
            "没有增加",
            "少了",
            "减少",
        ]
        time_or_state_words = ["现在", "今天", "这次", "后来", "又", "已经", "处理后", "复查", "观察"]
        if any(word in text for word in change_words) and (
            any(word in text for word in time_or_state_words) or context.case_status == CaseStatus.FOLLOWUP_PENDING
        ):
            return True
        return False

    def _tool_plan_for_intent(self, intent: str) -> list[str]:
        common = ["DateTool", "KnowledgeSearchTool", "DiagnosisTool", "SafetyChecker"]
        if intent in {"chemical_safety_question", "pesticide_detail_question"}:
            return [*common, "WeatherTool", "PlanTool", "CalendarReminderTool", "ResponseComposer"]
        if intent == "handling_plan_question":
            return [*common, "WeatherTool", "PlanTool", "CalendarReminderTool"]
        if intent == "diagnosis_correction_or_hypothesis":
            return [*common, "PlanTool", "CalendarReminderTool"]
        if intent == "followup_change_report":
            return ["DateTool", "FollowupCompareTool", "StateMachine", "CalendarReminderTool", "ResponseComposer"]
        return [*common, "PlanTool", "CalendarReminderTool"]
