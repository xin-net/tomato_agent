from app.domain.enums import AgentAction, CaseStatus
from app.schemas.agent import AgentDecision, AgentDecisionContext


class AgentDecisionEngine:
    def decide(self, context: AgentDecisionContext) -> AgentDecision:
        if context.case_status == CaseStatus.CLOSED:
            return AgentDecision(
                next_action=AgentAction.ESCALATE,
                reason="当前病例已结案，不能直接追加普通处置流程。",
                requested_state=CaseStatus.ESCALATED,
                confidence="medium",
            )

        if context.case_status == CaseStatus.FOLLOWUP_PENDING or context.active_followup:
            return AgentDecision(
                next_action=AgentAction.COMPARE_FOLLOWUP,
                reason="当前病例存在待复查任务，用户输入应作为复查信息进行比较。",
                requested_state=CaseStatus.FOLLOWUP_REVIEW,
                confidence="high",
            )

        missing = set(context.structured_symptoms.missing_fields)
        if {"发生部位", "生长阶段"}.issubset(missing) or len(missing) >= 3:
            return AgentDecision(
                next_action=AgentAction.ASK_MORE_INFO,
                reason="缺少发生部位、生长阶段、采收时间或近期用药等关键信息。",
                requested_state=CaseStatus.NEED_MORE_INFO,
                questions=[
                    "异常主要出现在老叶、新叶、叶背、茎、花还是果实？",
                    "斑点是什么颜色和形态？是否有同心轮纹或霉层？",
                    "番茄目前处于苗期、开花期、结果期还是采收期？",
                    "最近是否施肥、喷药，距离预计采收还有几天？",
                ],
                confidence="high",
            )

        return AgentDecision(
            next_action=AgentAction.DIAGNOSE_AND_PLAN,
            reason="当前信息足以形成保守的初步判断并创建复查计划。",
            requested_state=CaseStatus.FOLLOWUP_PENDING,
            confidence="medium",
        )
