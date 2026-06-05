from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class KPIChallengeBrief(BaseModel):
    challenge_key: UUID
    name: str
    description: str | None = None
    icon: str | None = None
    challenge_type: str | None = None
    target_value: int | None = None
    xp_reward: int | None = None
    is_daily: bool | None = None
    is_active: bool | None = None
    options: list[str] | None = None
    start_date: date
    end_date: date | None = None
    is_completed_today: bool = False
    value_logged_today: int | None = None


class KPIDashboardCard(BaseModel):
    kpi_key: UUID
    kpi_name: str
    latest_score: float
    previous_score: float | None = None
    trend_percent: float | None = None
    last_submission_at: datetime | None = None
    kpi_start_date: date | None = None
    kpi_end_date: date | None = None
    color: str | None = None
    icon: str | None = None
    challenges: list[KPIChallengeBrief] = []


class KPIDashboardResponse(BaseModel):
    items: list[KPIDashboardCard]
