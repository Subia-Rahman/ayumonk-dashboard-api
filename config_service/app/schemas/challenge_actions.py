from __future__ import annotations
from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class ChallengeActionRequest(BaseModel):
    challenge_id: UUID
    value_logged: int | None = Field(default=None, ge=0)
    toggle_value: bool | None = None
    choice_value: int | None = Field(default=None, ge=0)
    multi_values: list[int] | None = None
    timer_seconds: int | None = Field(default=None, ge=0)
    rating_value: int | None = Field(default=None, ge=0)


class StreakInfo(BaseModel):
    current_streak: int
    longest_streak: int
    last_completion_date: date
    streak_status: str  # "new" | "incremented" | "reset" | "already_done"


class XpInfo(BaseModel):
    xp_earned_now: int
    total_xp: int
    xp_this_week: int
    current_level: int
    level_label: str
    level_up: bool


class BadgeInfo(BaseModel):
    badge_key: str
    label: str
    icon: str
    level: str


class ChallengeActionResponse(BaseModel):
    message: str
    xp_earned: int
    status: str
    completion_date: date
    value_logged: int | None = None
    streak: StreakInfo | None = None
    xp: XpInfo | None = None
    badge_earned: bool = False
    badge: BadgeInfo | None = None


class ChallengeUndoRequest(BaseModel):
    challenge_id: UUID


class ChallengeUndoResponse(BaseModel):
    message: str
    challenge_id: UUID
    completion_date: date
    xp_deducted: int
    xp: XpInfo | None = None
    streak: StreakInfo | None = None


class DashboardChallengeStatus(BaseModel):
    challenge_id: UUID
    title: str
    kpi_key: UUID
    status: str
    value_logged: int | None = None
    xp_earned: int | None = None


class DashboardChallengesResponse(BaseModel):
    challenges: list[DashboardChallengeStatus]
