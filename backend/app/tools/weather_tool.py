from urllib.parse import urlencode
from urllib.request import urlopen

from pydantic import BaseModel, Field

from app.core.config import get_settings


class WeatherObservation(BaseModel):
    location: str
    location_source: str = "unknown"
    location_error: str | None = None
    requires_confirmation: bool = True
    latitude: float | None = None
    longitude: float | None = None
    recent_rain: bool | None = None
    humidity_risk: str | None = None
    temperature_summary: str | None = None
    current_temperature_c: float | None = None
    current_relative_humidity: float | None = None
    current_precipitation_mm: float | None = None
    current_wind_speed_kmh: float | None = None
    risk_signals: list[str] = Field(default_factory=list)
    provider: str = "manual_or_external"
    is_configured: bool = False
    status: str = "manual_only"
    uncertainties: list[str] = Field(default_factory=list)


class WeatherTool:
    name = "WeatherTool"
    description = "观察近期天气、湿度和温度风险信号，后续可接入外部天气 API。"

    def observe(
        self,
        location: str,
        user_description: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        location_source: str | None = None,
        location_error: str | None = None,
        explicit_weather: str | None = None,
    ) -> WeatherObservation:
        settings = get_settings()
        risk_signals: list[str] = []
        uncertainties: list[str] = []
        recent_rain = None
        humidity_risk = None
        temperature_summary = None
        temperature = None
        humidity = None
        precipitation = None
        wind_speed = None
        status = "manual_only"
        provider = "manual_or_external"

        description = "；".join(
            item for item in [user_description or "", explicit_weather or ""] if item
        )
        resolved_source = location_source or ("browser" if latitude is not None and longitude is not None else "manual")
        if any(word in description for word in ["连续阴雨", "下雨", "降雨", "雨后"]):
            recent_rain = True
            risk_signals.append("用户描述近期降雨或连续阴雨。")
        if any(word in description for word in ["高湿", "潮湿", "闷", "湿度大", "通风差"]):
            humidity_risk = "high"
            risk_signals.append("用户描述高湿或通风不良。")
        if any(word in description for word in ["高温", "太热", "暴晒"]):
            temperature_summary = "偏高"
            risk_signals.append("用户描述高温或暴晒环境。")
        if any(word in description for word in ["低温", "降温", "冷"]):
            temperature_summary = "偏低"
            risk_signals.append("用户描述低温或降温环境。")
        if latitude is not None and longitude is not None:
            provider = "open-meteo"
            try:
                current = self._fetch_open_meteo(latitude, longitude)
                status = "live_weather"
                temperature = current.get("temperature_2m")
                humidity = current.get("relative_humidity_2m")
                precipitation = current.get("precipitation")
                wind_speed = current.get("wind_speed_10m")
                if humidity is not None and humidity >= 85:
                    humidity_risk = "high"
                    risk_signals.append(f"实时相对湿度约 {humidity:.0f}%，高湿会增加病害扩展风险。")
                if precipitation is not None and precipitation > 0:
                    recent_rain = True
                    risk_signals.append(f"实时降水约 {precipitation:.1f} mm，叶面潮湿风险较高。")
                if temperature is not None:
                    if temperature >= 32:
                        temperature_summary = "偏高"
                        risk_signals.append(f"实时温度约 {temperature:.1f}℃，高温环境需注意通风和水分波动。")
                    elif temperature <= 12:
                        temperature_summary = "偏低"
                        risk_signals.append(f"实时温度约 {temperature:.1f}℃，低温环境可能影响恢复。")
            except Exception as exc:
                status = "weather_failed"
                uncertainties.append(f"实时天气获取失败：{exc}")
        else:
            if location_error:
                uncertainties.append(f"未获得浏览器定位：{location_error}。")
            else:
                uncertainties.append("未获得浏览器定位，天气工具只能根据用户文字描述判断。")
            if explicit_weather:
                status = "user_weather"
                provider = "user_description"

        return WeatherObservation(
            location=location,
            location_source=resolved_source,
            location_error=location_error,
            requires_confirmation=resolved_source != "user_explicit",
            latitude=latitude,
            longitude=longitude,
            recent_rain=recent_rain,
            humidity_risk=humidity_risk,
            temperature_summary=temperature_summary,
            current_temperature_c=temperature,
            current_relative_humidity=humidity,
            current_precipitation_mm=precipitation,
            current_wind_speed_kmh=wind_speed,
            risk_signals=risk_signals,
            provider=provider,
            is_configured=bool(settings.weather_api_key or (latitude is not None and longitude is not None)),
            status=status,
            uncertainties=uncertainties,
        )

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
        with urlopen(url, timeout=4) as response:
            import json

            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("current", {})
