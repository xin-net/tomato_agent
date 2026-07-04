from dataclasses import dataclass

from openai import OpenAI, OpenAIError

from app.core.config import get_settings


@dataclass(frozen=True)
class LLMResult:
    provider: str
    model: str
    content: str
    is_configured: bool


class OpenAIAdapter:
    def __init__(self):
        self.settings = get_settings()

    def complete(self, prompt: str, model: str | None = None) -> LLMResult:
        selected_model = model or self.settings.openai_text_model
        if not self.settings.openai_api_key:
            return LLMResult(
                provider="openai",
                model=selected_model,
                content="OpenAI API key is not configured. Returning deterministic placeholder.",
                is_configured=False,
            )
        try:
            client = OpenAI(api_key=self.settings.openai_api_key)
            response = client.responses.create(
                model=selected_model,
                input=prompt,
            )
            return LLMResult(
                provider="openai",
                model=selected_model,
                content=response.output_text,
                is_configured=True,
            )
        except OpenAIError as exc:
            return LLMResult(
                provider="openai",
                model=selected_model,
                content=f"OpenAI request failed: {exc}",
                is_configured=False,
            )
