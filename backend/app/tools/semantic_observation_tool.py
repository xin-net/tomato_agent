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
    location_text: str | None = None
    recent_weather: str | None = None
    growth_stage: str | None = None
    harvest_hint: str | None = None
    days_to_harvest: int | None = None
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
    description = "使用大模型理解用户本轮消息，结构化抽取地点、阶段、采收、复查变化、纠正和症状语义。"

    def __init__(self, llm: OpenAIAdapter | None = None):
        self.llm = llm or OpenAIAdapter()

    def observe(
        self,
        message: str,
        case_memory: dict[str, Any] | None = None,
        active_followup: dict[str, Any] | None = None,
        vision_observation: dict[str, Any] | None = None,
        date_observation: dict[str, Any] | None = None,
        history_summary: list[dict[str, Any]] | None = None,
    ) -> SemanticObservation:
        result = self.llm.complete(
            self._prompt(
                message=message,
                case_memory=case_memory or {},
                active_followup=active_followup,
                vision_observation=vision_observation,
                date_observation=date_observation,
                history_summary=history_summary or [],
            )
        )
        if not result.is_configured:
            return SemanticObservation(
                status="not_configured",
                is_configured=False,
                model=result.model,
                uncertainties=["语义观察模型不可用，不能可靠理解地点、阶段、采收或复查变化。"],
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
        vision_observation: dict[str, Any] | None,
        date_observation: dict[str, Any] | None,
        history_summary: list[dict[str, Any]],
    ) -> str:
        context = {
            "latest_user_message": message,
            "case_memory": case_memory,
            "active_followup": active_followup,
            "vision_observation": vision_observation,
            "date_observation": date_observation,
            "history_summary": history_summary,
        }
        return (
            "你是番茄病虫害处置闭环系统的语义观察工具。"
            "你的任务不是给最终诊断，而是理解用户本轮自然语言，并输出严格 JSON。"
            "必须依靠语义理解，不要做关键词匹配。汉语表达可能非常灵活。"
            "你需要判断：\n"
            "1. 用户本轮意图 user_intent，例如 initial_diagnosis、followup_report、correction、chemical_question、location_update、weather_update。\n"
            "2. 如果已有 active_followup，判断用户是否在描述复查/变化；例如“霉层增多了、黄斑扩大了、虫子忽然多了、看着好多了、没怎么变”都属于复查变化。\n"
            "3. 如果是复查变化，输出 followup_trend：IMPROVING、UNCHANGED、WORSENING、INSUFFICIENT_INFO 或 NEEDS_HUMAN_CONFIRMATION，并给 evidence。\n"
            "4. 抽取用户明确表达或可从上下文合理识别的种植地点 location_text。不要把“现在/正在”的“在”误当地点。\n"
            "5. 抽取近期天气 recent_weather、生长阶段 growth_stage、采收提示 harvest_hint、距离采收天数 days_to_harvest。\n"
            "6. 抽取发生部位、症状、问题类别、用户提到的候选问题、严重程度。\n"
            "7. 如果用户纠正了前面信息，把 corrections 写成字段到新值的对象。\n"
            "识别不出来就用 null 或空数组，不要编造；不确定写入 uncertainties。"
            "只输出 JSON 对象，不要 Markdown。"
            "字段必须包含：user_intent,is_followup_report,followup_trend,followup_evidence,"
            "location_text,recent_weather,growth_stage,harvest_hint,days_to_harvest,"
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
