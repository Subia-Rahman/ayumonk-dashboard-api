from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, validator


SnoozeDuration = Literal["1h", "4h", "24h"]


NOTIFICATION_TYPES = {
    "streak_alert",
    "badge_unlock",
    "challenge_pending",
    "program_ending",
    "new_program",
    "daily_challenge",
    "generic",
}


class NotificationCreateRequest(BaseModel):
    user_id: UUID
    company_id: Optional[UUID] = None
    type: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=255)
    body: Optional[str] = None
    icon: Optional[str] = Field(default=None, max_length=64)
    action_type: Optional[str] = Field(default=None, max_length=64)
    action_payload: Optional[dict[str, Any]] = None

    @validator("type")
    def validate_type(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in NOTIFICATION_TYPES:
            raise ValueError(
                f"Unknown notification type '{v}'. Allowed: {sorted(NOTIFICATION_TYPES)}"
            )
        return v


class NotificationSnoozeRequest(BaseModel):
    duration: SnoozeDuration


class NotificationActionRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=64)
    payload: Optional[dict[str, Any]] = None


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    company_id: Optional[UUID] = None
    type: str
    title: str
    body: Optional[str]
    icon: Optional[str]
    action_type: Optional[str]
    action_payload: Optional[dict[str, Any]]
    is_read: bool
    read_at: Optional[datetime]
    dismissed_at: Optional[datetime]
    snooze_until: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread: int
    skip: int
    limit: int


class UnreadCountResponse(BaseModel):
    unread: int


class BulkActionResponse(BaseModel):
    affected: int
