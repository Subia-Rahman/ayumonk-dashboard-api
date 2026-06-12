"""Schemas for `GET /api/v1/challenges/schedule`.

Returns the full kpi_challenges schedule timeline grouped two ways:

  * ``items`` — one row per kpi_challenges record with computed ``status``
    (active / upcoming / ended / paused), ``days_total``, ``days_elapsed``,
    ``days_remaining``, ``progress_pct``. Used by the per-challenge views:
      - Employee Challenges tab — Active Challenges grid (status='active')
      - Upcoming Programs Strip (status='upcoming')
      - Archived Programs view (status='ended')

  * ``kpi_summary`` — one row per ``DISTINCT kpi_key`` aggregating the
    challenges that belong to it (earliest_start, latest_end, status,
    challenge_count). Used by the spec's "Company-level KPI Program
    Schedule" calendar on the HR Analytics dashboard — render as a
    Gantt-style row-per-KPI timeline with a vertical "today" marker.

Status values mirror the spec's challenge state machine (section 6.4):
  paused   — kpi_challenges.is_active = FALSE (admin paused mid-run)
  upcoming — today < start_date
  ended    — end_date IS NOT NULL AND today > end_date
  active   — otherwise
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ChallengeScheduleItem(BaseModel):
    """One ``kpi_challenges`` row enriched with KPI / challenge / theme
    metadata and date-math derived fields."""

    kpi_challenge_id: UUID
    kpi_key: UUID
    kpi_label: str
    challenge_key: UUID
    challenge_label: str
    challenge_icon: Optional[str] = None
    challenge_type: str
    theme_key: Optional[UUID] = None
    theme_label: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    is_active: bool
    status: str  # active | upcoming | ended | paused
    days_total: Optional[int] = None       # NULL when end_date IS NULL (open-ended)
    days_elapsed: int
    days_remaining: Optional[int] = None   # NULL when end_date IS NULL
    progress_pct: Optional[Decimal] = None # NULL when end_date IS NULL

    model_config = ConfigDict(from_attributes=True)


class ChallengeKpiSummary(BaseModel):
    """One row per ``DISTINCT kpi_key`` in the schedule. Drives the
    spec's per-KPI HR calendar view (one bar per KPI spanning its
    earliest start to its latest end)."""

    kpi_key: UUID
    kpi_label: str
    earliest_start: date
    latest_end: Optional[date] = None   # NULL when any challenge under this KPI is open-ended
    status: str                          # rolled-up status across all challenges for the KPI
    challenge_count: int

    model_config = ConfigDict(from_attributes=True)


class ChallengeScheduleResponse(BaseModel):
    """Response envelope for ``GET /api/v1/challenges/schedule``."""

    items: list[ChallengeScheduleItem]
    kpi_summary: list[ChallengeKpiSummary]
