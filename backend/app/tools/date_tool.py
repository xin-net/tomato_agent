from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel


class DateObservation(BaseModel):
    today: str
    now: str
    timezone: str
    weekday: str


class DateTool:
    name = "DateTool"
    description = "读取当前日期和时间，供复查到期、提醒调整和采收安全判断使用。"

    def observe(self, timezone_name: str = "Asia/Shanghai") -> DateObservation:
        tz = ZoneInfo(timezone_name)
        now = datetime.now(tz)
        return DateObservation(
            today=now.date().isoformat(),
            now=now.isoformat(),
            timezone=timezone_name,
            weekday=now.strftime("%A"),
        )
