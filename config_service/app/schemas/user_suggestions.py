"""Schemas for the user-facing suggestions endpoints (Phase 4).

  * GET  /api/v1/suggestions/my
  * POST /api/v1/suggestions/{log_id}/action

These read from / write to ``user_suggestion_log``, which is populated
by ``SuggestionEngineService.compute_and_persist`` inside the
form-submission write path.
"""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# Action enum is constrained at the schema layer to mirror the DB CHECK
# constraint on user_suggestion_log.action.
SuggestionAction = Literal["done", "skipped", "saved"]


# ---------------------------------------------------------------------------
# GET /suggestions/my
# ---------------------------------------------------------------------------


class UserSuggestionItem(BaseModel):
    """One Lifestyle Suggestion card. Combines the durable
    ``user_suggestion_log`` row (log_id, action) with the resolved
    ``suggestions`` content (title, type, dosha, etc) so the UI gets
    the full card in a single round-trip."""

    # user_suggestion_log columns
    log_id: UUID
    response_id: str
    kpi_key: Optional[UUID] = None
    trigger_mode: str
    priority: int
    shown_at: datetime
    action: Optional[SuggestionAction] = None
    actioned_at: Optional[datetime] = None

    # Joined suggestion content
    suggestion_id: UUID
    suggestion_type: str           # aahar / vihar / aushadh
    title: str
    description: Optional[str] = None
    url: Optional[str] = None
    dosha_type: str
    difficulty: Optional[str] = None
    duration_mins: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class UserSuggestionsResponse(BaseModel):
    """Envelope for GET /suggestions/my — references the parent
    submission so the UI knows which form-submit context these picks
    are for (matches the WellnessIndex donut's ``response_id``)."""

    response_id: str
    submitted_at: datetime
    items: list[UserSuggestionItem]


# ---------------------------------------------------------------------------
# POST /suggestions/{log_id}/action
# ---------------------------------------------------------------------------


class SuggestionActionRequest(BaseModel):
    """Body for ``POST /suggestions/{log_id}/action``.

    Records what the user did with a served suggestion. ``actioned_at``
    is set server-side on the row; the schema is intentionally minimal."""

    action: SuggestionAction = Field(
        ..., description="One of 'done', 'skipped', 'saved'."
    )


class SuggestionActionResponse(BaseModel):
    """Confirmation payload after recording an action."""

    log_id: UUID
    action: SuggestionAction
    actioned_at: datetime

    model_config = ConfigDict(from_attributes=True)
