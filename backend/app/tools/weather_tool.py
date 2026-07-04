from pydantic import BaseModel, Field

from app.core.config import get_settings


class WeatherObservation(BaseModel):
    location: str
    recent_rain: bool | None = None
    humidity_risk: str | None = None
    temperature_summary: str | None = None
    risk_signals: list[str] = Field(default_factory=list)
    provider: str = "manual_or_external"
    is_configured: bool = False


class WeatherTool:
    def observe(self, location: str, user_description: str | None = None) -> WeatherObservation:
        settings = get_settings()
        risk_signals: list[str] = []
        recent_rain = None
        humidity_risk = None

        description = user_description or ""
        if any(word in description for word in ["连续阴雨", "下雨", "降雨"]):
            recent_rain = True
            risk_signals.append("用户描述近期降雨或连续阴雨。")
        if any(word in description for word in ["高湿", "潮湿", "闷"]):
            humidity_risk = "high"
            risk_signals.append("用户描述高湿或通风不良。")

        return WeatherObservation(
            location=location,
            recent_rain=recent_rain,
            humidity_risk=humidity_risk,
            risk_signals=risk_signals,
            is_configured=bool(settings.weather_api_key),
        )
