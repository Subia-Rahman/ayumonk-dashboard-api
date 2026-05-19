from datetime import datetime, time
from typing import Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, validator


SnoozeDuration = Literal["24h", "48h", "7d"]


REMINDER_TOGGLE_FIELDS = {
    "is_enabled",
    "email_enabled",
    "push_enabled",
    "whatsapp_enabled",
    "daily_challenge",
    "streak_alert",
    "program_ending",
    "new_program",
    "badge_milestone",
}


def _validate_timezone(tz: str) -> str:
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone: {tz}") from exc
    return tz


class ReminderSettingsBase(BaseModel):
    is_enabled: bool = True

    email_enabled: bool = True
    push_enabled: bool = False
    whatsapp_enabled: bool = False

    reminder_time: time = Field(default=time(20, 0))
    timezone: str = Field(default="UTC", max_length=64)

    daily_challenge: bool = True
    streak_alert: bool = True
    program_ending: bool = True
    new_program: bool = True
    badge_milestone: bool = True

    @validator("timezone")
    def validate_tz(cls, v: str) -> str:
        return _validate_timezone(v)


class ReminderSettingsCreateRequest(ReminderSettingsBase):
    pass


class ReminderSettingsUpdateRequest(BaseModel):
    is_enabled: Optional[bool] = None

    email_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None
    whatsapp_enabled: Optional[bool] = None

    reminder_time: Optional[time] = None
    timezone: Optional[str] = Field(default=None, max_length=64)

    daily_challenge: Optional[bool] = None
    streak_alert: Optional[bool] = None
    program_ending: Optional[bool] = None
    new_program: Optional[bool] = None
    badge_milestone: Optional[bool] = None

    @validator("timezone")
    def validate_tz(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _validate_timezone(v)


class ReminderSettingsToggleRequest(BaseModel):
    field: str = Field(..., description="Name of the boolean field to toggle")
    value: Optional[bool] = Field(
        default=None,
        description="If omitted, the current value is flipped.",
    )

    @validator("field")
    def validate_field(cls, v: str) -> str:
        if v not in REMINDER_TOGGLE_FIELDS:
            raise ValueError(
                f"Field '{v}' cannot be toggled. Allowed: {sorted(REMINDER_TOGGLE_FIELDS)}"
            )
        return v


class ReminderSettingsSnoozeRequest(BaseModel):
    duration: SnoozeDuration


class ReminderSettingsResponse(ReminderSettingsBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    snooze_until: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
