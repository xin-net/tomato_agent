from pydantic import BaseModel, Field
from openai import OpenAI, OpenAIError

from app.core.config import get_settings


class VisionObservation(BaseModel):
    observed_parts: list[str] = Field(default_factory=list)
    visual_symptoms: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    confidence: str = "low"
    provider: str = "openai"
    model: str
    is_configured: bool = False


class VisionTool:
    def analyze(self, image_urls: list[str], context: str = "") -> VisionObservation:
        settings = get_settings()
        if not settings.openai_api_key:
            return VisionObservation(
                model=settings.openai_vision_model,
                uncertainties=["OpenAI API key 未配置，MVP 当前仅保存图片证据，未执行视觉识别。"],
                suggested_questions=["请补充发生部位、病斑形态、是否有霉层或虫体。"],
                is_configured=False,
            )

        content: list[dict] = [
            {
                "type": "input_text",
                "text": (
                    "你是番茄病虫害处置系统的视觉观察工具，只输出可观察线索，不做最终诊断。"
                    "请用简短中文列出图片中可能的发生部位、可见症状、不确定点和建议追问。"
                    f"上下文：{context or '无'}"
                ),
            }
        ]
        for image_url in image_urls[:4]:
            content.append({"type": "input_image", "image_url": image_url})

        try:
            client = OpenAI(api_key=settings.openai_api_key)
            response = client.responses.create(
                model=settings.openai_vision_model,
                input=[{"role": "user", "content": content}],
            )
            text = response.output_text.strip()
            return VisionObservation(
                model=settings.openai_vision_model,
                visual_symptoms=[text] if text else [],
                uncertainties=["视觉结果是工具观察，仍需结合用户描述、状态机和安全检查。"],
                confidence="medium",
                is_configured=True,
            )
        except OpenAIError as exc:
            return VisionObservation(
                model=settings.openai_vision_model,
                uncertainties=[f"OpenAI 视觉工具调用失败：{exc}"],
                suggested_questions=["请补充发生部位、病斑形态、是否有霉层或虫体。"],
                is_configured=False,
            )
