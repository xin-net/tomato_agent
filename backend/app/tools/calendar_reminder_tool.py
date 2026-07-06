from datetime import date, datetime, time
from urllib.parse import urlencode

from pydantic import BaseModel, Field

from app.repositories.followup_repository import FollowupRepository
from app.repositories.reminder_repository import ReminderRepository
from app.schemas.reminders import ReminderCreate


class CalendarReminderResult(BaseModel):
    followup_id: int
    reminder_id: int | None = None
    due_date: str
    due_at: str
    channel: str = "in_app"
    mode: str
    checklist: list[str] = Field(default_factory=list)
    reason: str
    calendar_url: str | None = None
    ics_url: str | None = None


class CalendarReminderTool:
    name = "CalendarReminderTool"
    description = "创建或调整复查日程和系统内提醒；后续可适配 Google Calendar、系统日历或通知渠道。"

    def __init__(self, followups: FollowupRepository, reminders: ReminderRepository):
        self.followups = followups
        self.reminders = reminders

    def schedule_followup(
        self,
        case_id: int,
        due_date: date,
        checklist: list[str],
        reason: str,
        channel: str = "in_app",
    ) -> CalendarReminderResult:
        due_at = datetime.combine(due_date, time(hour=9))
        active_followup = self.followups.active_for_case(case_id)
        if active_followup:
            followup = self.followups.reschedule(active_followup, due_date, checklist)
            self.reminders.reschedule_for_followup(
                followup.id,
                due_at,
                reason,
                channel=channel,
            )
            reminder = self.reminders.pending_for_followup(followup.id)
            mode = "rescheduled"
        else:
            followup = self.followups.create(case_id, due_date, checklist)
            reminder = self.reminders.create(
                ReminderCreate(
                    case_id=case_id,
                    followup_id=followup.id,
                    due_at=due_at,
                    channel=channel,
                    reason=reason,
                )
            )
            mode = "created"

        calendar_url = self._google_calendar_url(due_at, reason)
        ics_url = f"/api/reminders/{reminder.id}/ics" if reminder else None
        return CalendarReminderResult(
            followup_id=followup.id,
            reminder_id=reminder.id if reminder else None,
            due_date=due_date.isoformat(),
            due_at=due_at.isoformat(),
            channel=channel,
            mode=mode,
            checklist=[str(item) for item in checklist],
            reason=reason,
            calendar_url=calendar_url,
            ics_url=ics_url,
        )

    def cancel_followup_reminder(self, followup_id: int) -> None:
        self.reminders.cancel_for_followup(followup_id)

    def _google_calendar_url(self, due_at: datetime, reason: str) -> str:
        start = due_at.strftime("%Y%m%dT%H%M%S")
        end = due_at.replace(hour=min(due_at.hour + 1, 23)).strftime("%Y%m%dT%H%M%S")
        query = urlencode(
            {
                "action": "TEMPLATE",
                "text": "番茄病例复查提醒",
                "dates": f"{start}/{end}",
                "details": reason,
            }
        )
        return f"https://calendar.google.com/calendar/render?{query}"
