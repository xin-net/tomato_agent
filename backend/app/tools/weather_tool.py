import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from app.core.config import get_settings


class WeatherObservation(BaseModel):
    location: str
    location_source: str = "unknown"
    adcode: str | None = None
    location_error: str | None = None
    requires_confirmation: bool = True
    latitude: float | None = None
    longitude: float | None = None
    weather: str | None = None
    temperature: str | None = None
    wind_direction: str | None = None
    wind_power: str | None = None
    humidity: str | None = None
    report_time: str | None = None
    current_temperature_c: float | None = None
    current_relative_humidity: float | None = None
    current_precipitation_mm: float | None = None
    current_wind_speed_kmh: float | None = None
    risk_signals: list[str] = Field(default_factory=list)
    provider: str = "amap"
    is_configured: bool = False
    status: str = "not_configured"
    uncertainties: list[str] = Field(default_factory=list)


class WeatherTool:
    name = "WeatherTool"
    description = "根据 LocationTool 输出的地点或 adcode 查询真实天气；不从用户文字中抽取天气。"

    def observe(
        self,
        location: str,
        adcode: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        location_source: str | None = None,
        location_error: str | None = None,
    ) -> WeatherObservation:
        settings = get_settings()
        key = settings.amap_web_service_key or settings.weather_api_key
        if key and adcode:
            try:
                live = self._fetch_amap_weather(key, adcode)
                return WeatherObservation(
                    location=location,
                    location_source=location_source or "unknown",
                    adcode=adcode,
                    location_error=location_error,
                    requires_confirmation=(location_source or "") not in {"user_explicit"},
                    latitude=latitude,
                    longitude=longitude,
                    weather=live.get("weather"),
                    temperature=live.get("temperature"),
                    wind_direction=live.get("winddirection"),
                    wind_power=live.get("windpower"),
                    humidity=live.get("humidity"),
                    report_time=live.get("reporttime"),
                    current_temperature_c=self._float_or_none(live.get("temperature")),
                    current_relative_humidity=self._float_or_none(live.get("humidity")),
                    risk_signals=[],
                    provider="amap",
                    is_configured=True,
                    status="live_weather",
                )
            except Exception as exc:
                return WeatherObservation(
                    location=location,
                    location_source=location_source or "unknown",
                    adcode=adcode,
                    location_error=location_error,
                    requires_confirmation=True,
                    latitude=latitude,
                    longitude=longitude,
                    provider="amap",
                    is_configured=True,
                    status="weather_failed",
                    uncertainties=[f"高德天气查询失败：{exc}"],
                )

        if latitude is not None and longitude is not None:
            try:
                current = self._fetch_open_meteo(latitude, longitude)
                return WeatherObservation(
                    location=location,
                    location_source=location_source or "browser",
                    adcode=adcode,
                    location_error=location_error,
                    requires_confirmation=True,
                    latitude=latitude,
                    longitude=longitude,
                    current_temperature_c=current.get("temperature_2m"),
                    current_relative_humidity=current.get("relative_humidity_2m"),
                    current_precipitation_mm=current.get("precipitation"),
                    current_wind_speed_kmh=current.get("wind_speed_10m"),
                    provider="open-meteo",
                    is_configured=True,
                    status="live_weather",
                )
            except Exception as exc:
                return WeatherObservation(
                    location=location,
                    location_source=location_source or "browser",
                    location_error=location_error,
                    requires_confirmation=True,
                    latitude=latitude,
                    longitude=longitude,
                    provider="open-meteo",
                    is_configured=True,
                    status="weather_failed",
                    uncertainties=[f"Open-Meteo 天气查询失败：{exc}"],
                )

        return WeatherObservation(
            location=location,
            location_source=location_source or "unknown",
            adcode=adcode,
            location_error=location_error,
            requires_confirmation=True,
            provider="amap",
            is_configured=bool(key),
            status="location_required" if key else "not_configured",
            uncertainties=[
                "缺少可用于天气查询的 adcode 或经纬度，需要用户补充实际种植地点。"
                if key
                else "未配置 AMAP_WEB_SERVICE_KEY，无法查询真实天气。"
            ],
        )

    def _fetch_amap_weather(self, key: str, adcode: str) -> dict:
        payload = self._amap_get(
            "https://restapi.amap.com/v3/weather/weatherInfo",
            {"key": key, "city": adcode, "extensions": "base", "output": "json"},
        )
        lives = payload.get("lives") or []
        if not lives:
            raise RuntimeError("高德天气没有返回 live 天气。")
        return lives[0]

    def _fetch_open_meteo(self, latitude: float, longitude: float) -> dict:
        query = urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m",
                "timezone": "auto",
            }
        )
        url = f"https://api.open-meteo.com/v1/forecast?{query}"
        with urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("current", {})

    def _amap_get(self, url: str, params: dict) -> dict:
        request = Request(f"{url}?{urlencode(params)}")
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if str(payload.get("status")) != "1":
            raise RuntimeError(payload.get("info") or "高德服务返回失败")
        return payload

    def _float_or_none(self, value) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
