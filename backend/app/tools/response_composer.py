import json

from app.schemas.cases import CaseResponse
from app.tools.llm_adapter import OpenAIAdapter


class ResponseComposer:
    def __init__(self, llm: OpenAIAdapter | None = None):
        self.llm = llm or OpenAIAdapter()

    def compose(self, response: CaseResponse) -> str:
        if not response.advice:
            return response.message

        result = self.llm.complete(self._prompt(response))
        if not result.is_configured or not result.content.strip():
            raise RuntimeError(f"ResponseComposer 模型不可用：{result.content}")
        return result.content.strip()

    def _prompt(self, response: CaseResponse) -> str:
        payload = response.model_dump(mode="json")
        intent = response.decision.user_intent if response.decision else "unknown"
        focus = response.decision.response_focus if response.decision else []
        return (
            "你是 Tomato Case Agent 的回复表达器，不是诊断器。"
            "你只能基于结构化结果回复，不能新增诊断、不能新增事实、不能改变状态、复查日期、处置建议或安全边界。"
            "必须优先回答用户本轮真正问的问题，语言自然、短、可执行，有结构但不要像 JSON、表格或报告。"
            "不能给具体农药名称、剂量、兑水比例、施药频次或混配处方。"
            "如果信息不足，温和追问；如果有复查安排，告诉用户后续直接描述变化即可。"
            "如果 environment_confirmation 有内容，自然提醒本轮按哪个地点/天气判断，并请用户确认实际种植地点是否一致。"
            "回复长度控制在 160-320 字。"
            f"\n本轮用户意图：{intent}"
            f"\n本轮回答焦点：{json.dumps(focus, ensure_ascii=False)}"
            f"\n结构化结果 JSON：{json.dumps(payload, ensure_ascii=False)}"
        )
