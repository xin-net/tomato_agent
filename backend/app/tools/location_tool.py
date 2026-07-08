import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.tools.llm_adapter import OpenAIAdapter


class LocationLanguageObservation(BaseModel):
    explicit_location: str | None = None
    confidence: str = "low"
    evidence: list[str] = []
    uncertainties: list[str] = []


class LocationObservation(BaseModel):
    location: str
    location_source: str
    adcode: str | None = None
    province: str | None = None
    city: str | None = None
    district: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_error: str | None = None
    requires_confirmation: bool = True
    note: str
    provider: str = "amap"
    language_confidence: str | None = None
    evidence: list[str] = []
    uncertainties: list[str] = []


class LocationTool:
    name = "LocationTool"
    description = "解析病例实际种植地点，用户明确地点优先；否则用高德 IP 定位或可用坐标兜底。"

    def __init__(self, llm: OpenAIAdapter | None = None):
        self.llm = llm or OpenAIAdapter()

    def observe(
        self,
        fallback_location: str = "用户未提供地点",
        user_message: str = "",
        browser_latitude: float | None = None,
        browser_longitude: float | None = None,
        browser_location_label: str | None = None,
        browser_location_source: str | None = None,
        browser_location_error: str | None = None,
        explicit_location: str | None = None,
        allow_fallback: bool = True,
    ) -> LocationObservation:
        language = self._observe_language_location(user_message) if user_message.strip() else None
        if not explicit_location and language and language.explicit_location:
            explicit_location = language.explicit_location

        if explicit_location:
            geocoded = self._geocode(explicit_location)
            return LocationObservation(
                location=geocoded.get("formatted_address") or explicit_location,
                location_source="user_explicit",
                adcode=geocoded.get("adcode"),
                province=geocoded.get("province"),
                city=geocoded.get("city"),
                district=geocoded.get("district"),
                latitude=geocoded.get("latitude"),
                longitude=geocoded.get("longitude"),
                requires_confirmation=False,
                note="用户本轮明确提供了种植地点，优先使用该地点。",
                language_confidence=language.confidence if language else None,
                evidence=language.evidence if language else [],
                uncertainties=geocoded.get("uncertainties", []) + (language.uncertainties if language else []),
            )

        if not allow_fallback:
            return LocationObservation(
                location=fallback_location,
                location_source="no_explicit_location_update",
                requires_confirmation=False,
                note="本轮只检查用户是否明确更新种植地点；未识别到明确地点，因此不使用自动定位兜底。",
                language_confidence=language.confidence if language else None,
                evidence=language.evidence if language else [],
                uncertainties=language.uncertainties if language else [],
            )

        if browser_latitude is not None and browser_longitude is not None:
            reverse = self._reverse_geocode(browser_latitude, browser_longitude)
            return LocationObservation(
                location=reverse.get("formatted_address") or browser_location_label or "当前位置附近",
                location_source=browser_location_source or "browser",
                adcode=reverse.get("adcode"),
                province=reverse.get("province"),
                city=reverse.get("city"),
                district=reverse.get("district"),
                latitude=browser_latitude,
                longitude=browser_longitude,
                requires_confirmation=True,
                note="使用客户端授权坐标作为增强定位；如果植株不在当前位置，需要用户纠正。",
                uncertainties=reverse.get("uncertainties", []) + (language.uncertainties if language else []),
            )

        ip_location = self._ip_location()
        if ip_location.get("location"):
            return LocationObservation(
                location=ip_location["location"],
                location_source="amap_ip",
                adcode=ip_location.get("adcode"),
                province=ip_location.get("province"),
                city=ip_location.get("city"),
                requires_confirmation=True,
                note="用户未提供地点，使用高德 IP 定位得到城市级位置；若植株不在此地，需要用户补充实际种植地点。",
                uncertainties=ip_location.get("uncertainties", []) + (language.uncertainties if language else []),
            )

        return LocationObservation(
            location=fallback_location,
            location_source=browser_location_source or "manual",
            location_error=browser_location_error or ip_location.get("error"),
            requires_confirmation=True,
            note="没有可靠地点，只能请求用户补充实际种植地点。",
            uncertainties=ip_location.get("uncertainties", []) + (language.uncertainties if language else []),
        )

    def _observe_language_location(self, message: str) -> LocationLanguageObservation:
        result = self.llm.complete(
            "你是番茄病虫害处置系统里的 LocationTool。"
            "你的唯一任务是判断用户本轮消息是否明确提供了番茄实际种植地点。"
            "不要判断天气、症状、复查趋势、生长阶段或采收时间。"
            "如果用户明确说出城市、区县、乡镇、村、大棚所在地、帮别人问且给出对方地点，填写 explicit_location。"
            "如果没有明确地点，explicit_location 必须为 null。"
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

    def _geocode(self, address: str) -> dict:
        settings = get_settings()
        key = settings.amap_web_service_key or settings.weather_api_key
        if not key:
            return {"uncertainties": ["未配置 AMAP_WEB_SERVICE_KEY，无法执行高德地理编码。"]}
        payload = self._amap_get(
            "https://restapi.amap.com/v3/geocode/geo",
            {"key": key, "address": address, "output": "json"},
        )
        geocodes = payload.get("geocodes") or []
        if not geocodes:
            return {"uncertainties": [f"高德未能解析地点：{address}。"]}
        item = geocodes[0]
        latitude = longitude = None
        if item.get("location"):
            lng, lat = item["location"].split(",", 1)
            longitude = float(lng)
            latitude = float(lat)
        return {
            "formatted_address": item.get("formatted_address") or address,
            "adcode": self._string_or_none(item.get("adcode")),
            "province": self._string_or_none(item.get("province")),
            "city": self._string_or_none(item.get("city")),
            "district": self._string_or_none(item.get("district")),
            "latitude": latitude,
            "longitude": longitude,
            "uncertainties": [],
        }

    def _reverse_geocode(self, latitude: float, longitude: float) -> dict:
        settings = get_settings()
        key = settings.amap_web_service_key or settings.weather_api_key
        if not key:
            return {"uncertainties": ["未配置 AMAP_WEB_SERVICE_KEY，无法执行高德逆地理编码。"]}
        payload = self._amap_get(
            "https://restapi.amap.com/v3/geocode/regeo",
            {
                "key": key,
                "location": f"{longitude},{latitude}",
                "output": "json",
                "extensions": "base",
            },
        )
        regeocode = payload.get("regeocode") or {}
        component = regeocode.get("addressComponent") or {}
        return {
            "formatted_address": regeocode.get("formatted_address"),
            "adcode": self._string_or_none(component.get("adcode")),
            "province": self._string_or_none(component.get("province")),
            "city": self._string_or_none(component.get("city")),
            "district": self._string_or_none(component.get("district")),
            "uncertainties": [],
        }

    def _ip_location(self) -> dict:
        settings = get_settings()
        key = settings.amap_web_service_key or settings.weather_api_key
        if not key:
            return {"uncertainties": ["未配置 AMAP_WEB_SERVICE_KEY，无法执行高德 IP 定位。"]}
        try:
            payload = self._amap_get(
                "https://restapi.amap.com/v3/ip",
                {"key": key, "output": "json"},
            )
        except Exception as exc:
            return {"error": str(exc), "uncertainties": [f"高德 IP 定位失败：{exc}"]}
        province = self._string_or_none(payload.get("province"))
        city = self._string_or_none(payload.get("city"))
        adcode = self._string_or_none(payload.get("adcode"))
        location = " ".join(part for part in [province, city] if part)
        if not location:
            return {"uncertainties": ["高德 IP 定位没有返回可用城市。"]}
        return {
            "location": location,
            "province": province,
            "city": city,
            "adcode": adcode,
            "uncertainties": [],
        }

    def _amap_get(self, url: str, params: dict) -> dict:
        request = Request(f"{url}?{urlencode(params)}")
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if str(payload.get("status")) != "1":
            raise RuntimeError(payload.get("info") or "高德服务返回失败")
        return payload

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

    def _string_or_none(self, value) -> str | None:
        if value is None or value == "" or value == []:
            return None
        return str(value)
