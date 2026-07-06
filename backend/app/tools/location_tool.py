import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError

from app.tools.llm_adapter import OpenAIAdapter


class LocationLanguageObservation(BaseModel):
    explicit_location: str | None = None
    confidence: str = "low"
    evidence: list[str] = []
    uncertainties: list[str] = []


class LocationObservation(BaseModel):
    location: str
    location_source: str
    latitude: float | None = None
    longitude: float | None = None
    location_error: str | None = None
    requires_confirmation: bool = True
    note: str
    language_confidence: str | None = None
    evidence: list[str] = []
    uncertainties: list[str] = []


class LocationTool:
    name = "LocationTool"
    description = "解析本轮病例应该使用的种植地点，处理用户显式地点、病例记忆、浏览器定位和反向地理编码。"

    def __init__(self, llm: OpenAIAdapter | None = None):
        self.llm = llm or OpenAIAdapter()

    def observe(
        self,
        fallback_location: str,
        user_message: str = "",
        browser_latitude: float | None = None,
        browser_longitude: float | None = None,
        browser_location_label: str | None = None,
        browser_location_source: str | None = None,
        browser_location_error: str | None = None,
        explicit_location: str | None = None,
        previous_location: str | None = None,
        previous_location_source: str | None = None,
    ) -> LocationObservation:
        language = self._observe_language_location(user_message) if user_message.strip() else None
        if not explicit_location and language and language.explicit_location:
            explicit_location = language.explicit_location

        if explicit_location:
            return LocationObservation(
                location=explicit_location,
                location_source="user_explicit",
                requires_confirmation=False,
                note="用户本轮明确提供了种植地点，覆盖浏览器当前位置。",
                language_confidence=language.confidence if language else None,
                evidence=language.evidence if language else [],
                uncertainties=language.uncertainties if language else [],
            )

        if previous_location and previous_location_source == "user_explicit":
            return LocationObservation(
                location=previous_location,
                location_source="case_memory_user_location",
                requires_confirmation=True,
                note="沿用该病例之前由用户明确提供的种植地点。",
                uncertainties=language.uncertainties if language else [],
            )

        if browser_latitude is not None and browser_longitude is not None:
            generic_browser_label = browser_location_label in {None, "", "浏览器定位", "当前位置附近"}
            resolved_location = (
                self._reverse_geocode(browser_latitude, browser_longitude)
                if generic_browser_label
                else browser_location_label
            )
            return LocationObservation(
                location=resolved_location or browser_location_label or "当前位置附近",
                location_source=browser_location_source or "browser",
                latitude=browser_latitude,
                longitude=browser_longitude,
                requires_confirmation=True,
                note="使用浏览器授权返回的当前位置；如果植株不在当前位置，需要用户纠正。",
                uncertainties=language.uncertainties if language else [],
            )

        return LocationObservation(
            location=fallback_location,
            location_source=browser_location_source or "manual",
            location_error=browser_location_error,
            requires_confirmation=True,
            note="没有可用坐标，只能按用户文字和病例环境线索判断。",
            uncertainties=language.uncertainties if language else [],
        )

    def _observe_language_location(self, message: str) -> LocationLanguageObservation:
        result = self.llm.complete(
            "你是番茄病虫害处置系统里的 LocationTool。"
            "你的唯一任务是判断用户本轮消息是否明确提供了番茄实际种植地点。"
            "不要判断天气、症状、复查趋势、生长阶段或采收时间。"
            "不要把“现在、正在、看起来、长了更多”里的“在”当成地点。"
            "只有用户明确说出城市、区县、乡镇、村、大棚所在地、帮别人问且给出对方地点等，才填写 explicit_location。"
            "如果只是浏览器定位、当前位置、没有地名、或表达不清楚，explicit_location 必须为 null。"
            "只输出 JSON：explicit_location, confidence, evidence, uncertainties。"
            f"\n用户本轮消息：{message}"
        )
        if not result.is_configured:
            return LocationLanguageObservation(
                uncertainties=["地点语言模型不可用，未从本轮文字中识别显式种植地点。"]
            )
        try:
            payload = self._parse_json(result.content)
            return LocationLanguageObservation.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            return LocationLanguageObservation(
                uncertainties=[f"地点语言模型输出无法解析：{exc}"]
            )

    def _reverse_geocode(self, latitude: float, longitude: float) -> str | None:
        query = urlencode(
            {
                "format": "jsonv2",
                "lat": latitude,
                "lon": longitude,
                "accept-language": "zh-CN",
            }
        )
        request = Request(
            f"https://nominatim.openstreetmap.org/reverse?{query}",
            headers={"User-Agent": "tomato-agent-dev/1.0"},
        )
        try:
            with urlopen(request, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None

        address = payload.get("address") or {}
        parts = [
            address.get("state"),
            address.get("city") or address.get("town") or address.get("county"),
            address.get("district") or address.get("suburb"),
        ]
        compact = [str(part) for part in parts if part]
        if compact:
            return " ".join(dict.fromkeys(compact))
        return payload.get("display_name")

    def _parse_json(self, content: str) -> dict:
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
