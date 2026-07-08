import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.domain.enums import FollowupTrend
from app.tools.llm_adapter import OpenAIAdapter


class SemanticObservation(BaseModel):
    status: str = "not_configured"
    is_configured: bool = False
    model: str | None = None
    user_intent: str = "unknown"
    is_followup_report: bool = False
    followup_trend: FollowupTrend | None = None
    followup_evidence: list[str] = Field(default_factory=list)
    affected_parts: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    possible_categories: list[str] = Field(default_factory=list)
    mentioned_problems: list[str] = Field(default_factory=list)
    severity: str | None = None
    corrections: dict[str, Any] = Field(default_factory=dict)
    uncertainties: list[str] = Field(default_factory=list)
    confidence: str = "low"
    raw_text: str | None = None


class SemanticObservationTool:
    name = "SemanticObservationTool"
    description = "使用大模型理解用户本轮消息，结构化判断复查变化、用户纠正、意图和症状语义。"

    def __init__(self, llm: OpenAIAdapter | None = None):
        self.llm = llm or OpenAIAdapter()

    def observe(
        self,
        message: str,
        case_memory: dict[str, Any] | None = None,
        active_followup: dict[str, Any] | None = None,
        date_observation: dict[str, Any] | None = None,
        history_summary: list[dict[str, Any]] | None = None,
    ) -> SemanticObservation:
        result = self.llm.complete(
            self._prompt(
                message=message,
                case_memory=case_memory or {},
                active_followup=active_followup,
                date_observation=date_observation,
                history_summary=history_summary or [],
            )
        )
        if not result.is_configured:
            return SemanticObservation(
                status="not_configured",
                is_configured=False,
                model=result.model,
                uncertainties=["语义观察模型不可用，不能可靠理解本轮意图、复查变化或症状语义。"],
            )

        try:
            payload = self._parse_json(result.content)
            return SemanticObservation.model_validate(
                {
                    **payload,
                    "status": "analyzed",
                    "is_configured": True,
                    "model": result.model,
                    "raw_text": result.content,
                }
            )
        except (ValueError, ValidationError) as exc:
            return SemanticObservation(
                status="failed",
                is_configured=False,
                model=result.model,
                uncertainties=[f"语义观察模型输出无法解析：{exc}"],
                raw_text=result.content,
            )

    def _prompt(
        self,
        message: str,
        case_memory: dict[str, Any],
        active_followup: dict[str, Any] | None,
        date_observation: dict[str, Any] | None,
        history_summary: list[dict[str, Any]],
    ) -> str:
        context = {
            "latest_user_message": message,
            "case_memory": case_memory,
            "active_followup": active_followup,
            "date_observation": date_observation,
            "history_summary": history_summary,
        }
        return (
            "你是番茄病虫害处置闭环系统的语义观察工具。"
            "你的任务不是给最终诊断，而是理解用户本轮自然语言，并输出严格 JSON。"
            "只根据 latest_user_message、本病例已有文字记忆、复查计划和历史摘要来判断本轮语义；"
            "不要依赖图片工具、天气工具或地点工具的输出。"
            "必须依靠语义理解，不要做关键词匹配或固定话术匹配。汉语表达可能非常灵活。"
            "你不负责地理编码、真实天气查询、图片阶段或采收视觉判断："
            "地点标准化由 LocationTool 做，天气由 WeatherTool 查询，图片中的阶段/采收由 VisionTool 判断。"
            "但如果用户在语义上明确提供或纠正种植地点、天气事实、生长阶段或采收时间，必须把它们放进 corrections，不要另设顶层字段。"
            "例如用户说“在天津市”“实际种植地是天津”“不是武侯区，是天津”，应写 corrections.location_text。"
            "你需要判断：\n"
            "1. 用户本轮意图 user_intent，例如 initial_diagnosis、followup_report、correction、chemical_question、pesticide_detail_question、handling_plan_question、location_update、weather_update。\n"
            "2. 如果已有 active_followup，判断用户是否在描述后续观察/变化。不要因为有 active_followup 就默认本轮是复查，也不要因为用户没有说“复查”两个字就否认变化报告。\n"
            "3. 如果是复查变化，输出 followup_trend：IMPROVING、UNCHANGED、WORSENING、INSUFFICIENT_INFO 或 NEEDS_HUMAN_CONFIRMATION，并给 evidence。\n"
            "   趋势判断要比较“本轮描述相对病例记忆中的上一状态”是好转、稳定、加重还是信息不足；不要被单个字词左右。\n"
            "4. 抽取本轮文字中表达的发生部位、症状语义、问题类别、用户提到的候选问题、严重程度。\n"
            "5. 如果用户纠正了前面信息，把 corrections 写成字段到新值的对象，例如 suspected_problem、growth_stage、days_to_harvest、recent_weather、location_text。\n"
            "corrections 中的 days_to_harvest 必须是整数天数；如果用户说“10天”，输出 10；无法确定则输出 null。"
            "识别不出来就用 null 或空数组，不要编造；不确定写入 uncertainties。"
            "只输出 JSON 对象，不要 Markdown。"
            "字段必须包含：user_intent,is_followup_report,followup_trend,followup_evidence,"
            "affected_parts,symptoms,possible_categories,mentioned_problems,severity,corrections,uncertainties,confidence。"
            f"\n上下文 JSON：{json.dumps(context, ensure_ascii=False)}"
        )

    def _parse_json(self, content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("未找到 JSON 对象")
        return json.loads(text[start : end + 1])
