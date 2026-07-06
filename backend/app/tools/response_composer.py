import json

from app.schemas.cases import CaseResponse
from app.tools.llm_adapter import OpenAIAdapter


class ResponseComposer:
    def __init__(self, llm: OpenAIAdapter | None = None):
        self.llm = llm or OpenAIAdapter()

    def compose(self, response: CaseResponse) -> str:
        if not response.advice:
            return response.message

        fallback = self._fallback(response)
        result = self.llm.complete(self._prompt(response, fallback))
        if not result.is_configured or not result.content.strip():
            return fallback
        return result.content.strip()

    def _prompt(self, response: CaseResponse, fallback: str) -> str:
        payload = response.model_dump(mode="json")
        intent = response.decision.user_intent if response.decision else "unknown"
        focus = response.decision.response_focus if response.decision else []
        return (
            "你是一个懂番茄种植、说话自然的助手。请把下面的结构化诊断和处置结果，"
            "改写成普通用户能听懂的中文回复。"
            "要求：像聊天一样自然，但要有结构，使用 2-4 个短小段落或少量项目符号；不要像 JSON、表格或报告；"
            "不要堆字段名；不要说系统内部原理；"
            "必须优先回答本轮用户真正问的问题，不要每一轮都重复首次诊断。"
            "如果 user_intent 是 chemical_safety_question 或 pesticide_detail_question，开头直接回答能不能用药/能不能给具体药，"
            "只用一句话带过已知疑似问题，不要重新展开完整病因、依据和复查闭环。"
            "必须保留安全边界，不能添加具体农药名称、剂量、兑水比例或施药频次；"
            "不能改变诊断结论、处置建议、采收安全提醒和复查安排；"
            "如果用户信息不足，要温和追问；如果有复查计划，要告诉用户后续直接描述变化即可。"
            "如果 environment_confirmation 有内容，必须自然地用一句话告诉用户：本轮按哪个地点/天气判断，并请确认实际种植地点是否一致。"
            "回复长度控制在 160-320 字。"
            f"\n本轮用户意图：{intent}"
            f"\n本轮回答焦点：{json.dumps(focus, ensure_ascii=False)}"
            f"\n结构化结果 JSON：{json.dumps(payload, ensure_ascii=False)}"
            f"\n不用大模型时的参考回复：{fallback}"
        )

    def _fallback(self, response: CaseResponse) -> str:
        advice = response.advice
        if advice is None:
            return response.message
        if not advice.information_sufficient:
            questions = response.decision.questions if response.decision else []
            question_text = " ".join(f"{index + 1}. {question}" for index, question in enumerate(questions))
            environment = f" {advice.environment_confirmation}" if advice.environment_confirmation else ""
            return (
                f"{advice.plain_summary} 我先不急着给你定病名，避免处理方向跑偏。"
                f"现在先别自行用药，拍清楚异常部位和整株情况。{environment}{question_text}"
            ).strip()

        diagnosis = response.diagnosis.suspected_problem if response.diagnosis else None
        intent = response.decision.user_intent if response.decision else "initial_diagnosis"
        if intent == "chemical_safety_question":
            return self._chemical_safety_fallback(response, diagnosis)
        if intent == "pesticide_detail_question":
            return self._pesticide_detail_fallback(response, diagnosis)

        problem_text = f"更像是 {diagnosis}" if diagnosis else advice.plain_summary
        actions = "、".join(advice.immediate_actions[:4]) or "先做保守处理"
        observe = "、".join(advice.observation_points[:4]) or "有没有新增、扩大或扩散"
        followup = advice.followup_timing or "后续继续观察变化"
        environment = f"\n\n**地点和天气**\n{advice.environment_confirmation}" if advice.environment_confirmation else ""
        return (
            f"**先说判断**\n我看了一下，{problem_text}，但先按保守判断处理。\n\n"
            f"**现在先做**\n- {actions}\n\n"
            f"**接下来观察**\n重点看{observe}。{advice.chemical_advice} {advice.harvest_safety}\n"
            f"我会继续按这个病例跟踪：{followup}。{environment}"
        )

    def _chemical_safety_fallback(self, response: CaseResponse, diagnosis: str | None) -> str:
        advice = response.advice
        if advice is None:
            return response.message
        problem = f"前面更像 {diagnosis}，" if diagnosis else ""
        actions = "、".join(advice.immediate_actions[:3]) or "先做非化学处理"
        observe = "、".join(advice.observation_points[:3]) or "有没有扩散、虫量是否增加、果实是否受影响"
        return (
            "**关于能不能用药**\n"
            f"{problem}但你说大概还有一周采收，这时我不建议直接给具体用药方案。"
            f"{advice.harvest_safety}\n\n"
            "**现在更稳妥的做法**\n"
            f"- 先做非化学处理：{actions}\n"
            f"- 继续观察：{observe}\n\n"
            "如果确实要用药，建议拿着实物或照片问当地农技人员，并核对当地登记标签和采前安全间隔期。"
            + (f"\n\n{advice.environment_confirmation}" if advice.environment_confirmation else "")
        )

    def _pesticide_detail_fallback(self, response: CaseResponse, diagnosis: str | None) -> str:
        advice = response.advice
        if advice is None:
            return response.message
        actions = "、".join(advice.immediate_actions[:3]) or "先做非化学处理"
        return (
            "**具体用什么药**\n"
            "我这里不能直接给你具体农药名称、剂量、兑水比例或施药频次，尤其你前面说离采收大概一周，"
            "这会涉及当地登记标签和采前安全间隔期。\n\n"
            "**我能给你的安全建议**\n"
            f"- 先按非化学方式处理：{actions}\n"
            "- 如果虫量继续上升或扩散到更多叶片，再联系当地农技人员确认可用药剂和安全间隔期。\n"
            f"{advice.harvest_safety}"
            + (f"\n\n{advice.environment_confirmation}" if advice.environment_confirmation else "")
        )
