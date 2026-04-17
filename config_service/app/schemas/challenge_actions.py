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


class ChallengeActionResponse(BaseModel):
    message: str
    xp_earned: int
    status: str
    completion_date: date
    value_logged: int | None = None


class DashboardChallengeStatus(BaseModel):
    challenge_id: UUID
    title: str
    kpi_key: UUID
    status: str
    value_logged: int | None = None
    xp_earned: int | None = None


class DashboardChallengesResponse(BaseModel):
    challenges: list[DashboardChallengeStatus]
