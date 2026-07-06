import json

from openai import APIStatusError, OpenAI, OpenAIError
from pydantic import BaseModel, Field

from app.core.config import get_settings


class VisionObservation(BaseModel):
    observed_parts: list[str] = Field(default_factory=list)
    visual_symptoms: list[str] = Field(default_factory=list)
    possible_problems: list[str] = Field(default_factory=list)
    severity_signals: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    growth_stage_hint: str | None = None
    harvest_hint: str | None = None
    confidence: str = "low"
    provider: str = "openai"
    model: str
    is_configured: bool = False
    status: str = "not_configured"
    raw_text: str | None = None


class VisionTool:
    observation_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "observed_parts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "图片中能直接观察到的番茄植株部位。",
            },
            "visual_symptoms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "图片中能直接观察到的症状、虫体、病斑或环境线索。",
            },
            "possible_problems": {
                "type": "array",
                "items": {"type": "string"},
                "description": "仅基于视觉线索的候选问题，不作为最终诊断。",
            },
            "severity_signals": {
                "type": "array",
                "items": {"type": "string"},
                "description": "图片中能看出的严重程度线索，如扩散、多部位受害、果实受害等。",
            },
            "uncertainties": {
                "type": "array",
                "items": {"type": "string"},
                "description": "图片无法确认或需要用户补充的信息。",
            },
            "suggested_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "为了降低误判，需要继续追问用户的问题。",
            },
            "growth_stage_hint": {
                "type": ["string", "null"],
                "description": "仅基于图片、季节和常见种植习惯推测的生长阶段，如苗期、开花期、结果期、采收期；无法判断则为 null。",
            },
            "harvest_hint": {
                "type": ["string", "null"],
                "description": "仅基于图片和上下文推测的采收接近程度，如临近采收、采收期、距离采收较远；无法判断则为 null。",
            },
            "confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "仅表示视觉观察的清晰度和可信度。",
            },
        },
        "required": [
            "observed_parts",
            "visual_symptoms",
            "possible_problems",
            "severity_signals",
            "uncertainties",
            "suggested_questions",
            "growth_stage_hint",
            "harvest_hint",
            "confidence",
        ],
    }

    def analyze(self, image_urls: list[str], context: str = "") -> VisionObservation:
        settings = get_settings()
        provider = settings.vision_provider.lower()
        if provider in {"none", "disabled"}:
            return VisionObservation(
                provider=provider,
                model=settings.openai_vision_model,
                uncertainties=["视觉识别已关闭，当前仅保存图片证据。"],
                suggested_questions=["请补充发生部位、病斑形态、是否有霉层或虫体。"],
                is_configured=False,
                status="not_configured",
            )
        if provider == "deepseek":
            return VisionObservation(
                provider="deepseek",
                model=settings.deepseek_text_model,
                uncertainties=[
                    "DeepSeek 官方 API 当前未提供图片输入/视觉识别能力，不能直接分析上传图片。"
                ],
                suggested_questions=["请用文字补充图片中看到的发生部位、颜色、斑点形态、虫体或霉层。"],
                is_configured=False,
                status="not_supported",
            )
        if provider != "openai":
            return VisionObservation(
                provider=provider,
                model=settings.openai_vision_model,
                uncertainties=[f"未知视觉模型提供方：{settings.vision_provider}。"],
                suggested_questions=["请补充发生部位、病斑形态、是否有霉层或虫体。"],
                is_configured=False,
                status="not_configured",
            )
        if not settings.openai_api_key:
            return VisionObservation(
                model=settings.openai_vision_model,
                uncertainties=["OpenAI API key 未配置，MVP 当前仅保存图片证据，未执行视觉识别。"],
                suggested_questions=["请补充发生部位、病斑形态、是否有霉层或虫体。"],
                is_configured=False,
                status="not_configured",
            )

        content: list[dict] = [
            {
                "type": "input_text",
                "text": (
                    "你是番茄病虫害处置闭环系统中的视觉观察工具。"
                    "你的任务是观察图片，不直接生成最终诊断和处置方案。"
                    "请只基于图片可见内容输出结构化 JSON：发生部位、可见症状、候选问题、严重程度线索、不确定点和建议追问。"
                    "如果图片不清晰或无法确认，请明确写入 uncertainties，不要编造。"
                    f"上下文：{context or '无'}"
                ),
            }
        ]
        for image_url in image_urls[:4]:
            content.append({"type": "input_image", "image_url": image_url})

        try:
            client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url or None,
            )
            response = client.responses.create(
                model=settings.openai_vision_model,
                input=[{"role": "user", "content": content}],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "tomato_vision_observation",
                        "strict": True,
                        "schema": self.observation_schema,
                    }
                },
            )
            text = response.output_text.strip()
            payload = json.loads(text) if text else {}
            return VisionObservation(
                model=settings.openai_vision_model,
                observed_parts=payload.get("observed_parts", []),
                visual_symptoms=payload.get("visual_symptoms", []),
                possible_problems=payload.get("possible_problems", []),
                severity_signals=payload.get("severity_signals", []),
                uncertainties=payload.get("uncertainties", [])
                + ["视觉结果是工具观察，仍需结合用户描述、状态机和安全检查。"],
                suggested_questions=payload.get("suggested_questions", []),
                growth_stage_hint=payload.get("growth_stage_hint"),
                harvest_hint=payload.get("harvest_hint"),
                confidence=payload.get("confidence", "medium"),
                is_configured=True,
                status="analyzed",
                raw_text=text,
            )
        except json.JSONDecodeError:
            return VisionObservation(
                model=settings.openai_vision_model,
                uncertainties=["OpenAI 视觉工具返回了无法解析的结构化结果，请稍后重试。"],
                suggested_questions=["请补充发生部位、病斑形态、是否有霉层或虫体。"],
                is_configured=False,
                status="failed",
            )
        except OpenAIError as exc:
            return VisionObservation(
                model=settings.openai_vision_model,
                uncertainties=[f"OpenAI 视觉工具调用失败：{self._safe_openai_error(exc)}"],
                suggested_questions=["请补充发生部位、病斑形态、是否有霉层或虫体。"],
                is_configured=False,
                status="failed",
            )

    def _safe_openai_error(self, exc: OpenAIError) -> str:
        if isinstance(exc, APIStatusError):
            if exc.status_code == 401:
                return "认证失败，请检查 OPENAI_API_KEY 是否有效。"
            if exc.status_code == 403:
                return "当前 API Key 没有访问该模型或接口的权限。"
            if exc.status_code == 429:
                return "请求过于频繁或额度不足，请稍后重试或检查账户额度。"
            return f"请求失败，HTTP 状态码 {exc.status_code}。"
        return "请求失败，请检查网络、API 地址或模型配置。"
