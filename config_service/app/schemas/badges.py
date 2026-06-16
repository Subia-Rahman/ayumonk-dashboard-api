from __future__ import annotations
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class BadgeWithStatus(BaseModel):
    """One badge tile in the user's badge cabinet — earned or locked."""
    badge_key: str
    label: str
    icon: str
    level: str            # bronze | silver | gold | legend (display tier)
    trigger_type: str     # streak | kpi_completions | level
    trigger_value: int
    kpi_key: UUID | None
    kpi_display_name: str | None  # populated only for kpi-scoped badges
    earned: bool
    earned_at: datetime | None


class MyBadgesResponse(BaseModel):
    badges: list[BadgeWithStatus]
    earned_count: int
    total_count: int
