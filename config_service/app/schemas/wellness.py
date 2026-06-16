from __future__ import annotations
"""Schemas for the wellness endpoints (Phase 3).

  * GET  /api/v1/wellness/index — donut centre + risk band + delta
  * POST /api/v1/wellness/mood  — 5-emoji daily check-in
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# GET /wellness/index
# ---------------------------------------------------------------------------


class WellnessIndexResponse(BaseModel):
    """Headline Wellness Index for the caller, fetched from the most
    recent ``theme_submission_scores`` row.

    ``week_delta`` is the change vs the previous submission's score
    (signed Decimal; NULL on the very first submission). The donut
    badge renders ``▲ {delta} from baseline`` when positive, ``▼`` when
    negative.
    """

    overall_score: Decimal               # 0-100
    risk_level: str                      # excellent / good / moderate / attention
    week_delta: Optional[Decimal] = None
    computed_at: datetime                # created_at of the row
    response_id: str                     # parent submission anchor
    theme_key: Optional[UUID] = None     # NULL until Phase 5 (company_themes)

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# POST /wellness/mood
# ---------------------------------------------------------------------------


class WellnessMoodRequest(BaseModel):
    """Body for ``POST /wellness/mood`` — a single emoji tap.

    1=😞 / 2=😕 / 3=😐 / 4=🙂 / 5=😄. Constrained at the schema layer
    to match the CHECK constraint on ``user_mood_log.score``.
    """

    score: int = Field(..., ge=1, le=5, description="1-5 emoji rating")


class WellnessMoodResponse(BaseModel):
    """Confirmation payload returned after persisting a mood row."""

    id: UUID
    score: int
    logged_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WellnessMoodTodayResponse(BaseModel):
    """Response for ``GET /api/v1/wellness/mood/today``.

    ``logged`` is the authoritative per-user "have I logged mood
    today?" flag — derived from ``user_mood_log`` filtered by the JWT
    subject's email + current date. Replaces frontend localStorage
    which leaks between users on a shared browser.

    When ``logged=True``, the other fields carry the row's details so
    the UI can render the locked card with the user's actual emoji
    selection. When ``logged=False``, the other fields are NULL."""

    logged: bool
    id: Optional[UUID] = None
    score: Optional[int] = None
    logged_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
