from dataclasses import dataclass

from openai import APIStatusError, OpenAI, OpenAIError

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
        provider = self.settings.llm_provider.lower()
        selected_model = model or self._default_model(provider)
        api_key = self._api_key(provider)
        if not api_key:
            return LLMResult(
                provider=provider,
                model=selected_model,
                content=f"{provider} API key is not configured. Returning deterministic placeholder.",
                is_configured=False,
            )
        try:
            client = OpenAI(
                api_key=api_key,
                base_url=self._base_url(provider),
            )
            if provider == "deepseek":
                response = client.chat.completions.create(
                    model=selected_model,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = response.choices[0].message.content or ""
            else:
                response = client.responses.create(
                    model=selected_model,
                    input=prompt,
                )
                content = response.output_text
            return LLMResult(
                provider=provider,
                model=selected_model,
                content=content,
                is_configured=True,
            )
        except OpenAIError as exc:
            return LLMResult(
                provider=provider,
                model=selected_model,
                content=f"{provider} request failed: {self._safe_openai_error(exc, provider)}",
                is_configured=False,
            )

    def _default_model(self, provider: str) -> str:
        if provider == "deepseek":
            return self.settings.deepseek_text_model
        return self.settings.openai_text_model

    def _api_key(self, provider: str) -> str | None:
        if provider == "deepseek":
            return self.settings.deepseek_api_key
        return self.settings.openai_api_key

    def _base_url(self, provider: str) -> str | None:
        if provider == "deepseek":
            return self.settings.deepseek_base_url
        return self.settings.openai_base_url or None

    def _safe_openai_error(self, exc: OpenAIError, provider: str) -> str:
        if isinstance(exc, APIStatusError):
            if exc.status_code == 401:
                key_name = "DEEPSEEK_API_KEY" if provider == "deepseek" else "OPENAI_API_KEY"
                return f"authentication failed; check {key_name}."
            if exc.status_code == 403:
                return "the API key cannot access this model or endpoint."
            if exc.status_code == 429:
                return "rate limit or quota exceeded."
            return f"HTTP {exc.status_code}."
        return "request failed; check network, API base URL, or model settings."
