from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator


# trigger_type values understood by the award engine. Keep in sync with
# services/challenge_actions.py:_award_badges.
TriggerType = Literal["streak", "kpi_completions", "level"]

# Display tier — purely cosmetic, used by the UI for tile colouring.
LEVEL_VALUES = {"bronze", "silver", "gold", "legend", "platinum"}


class BadgeCreateRequest(BaseModel):
    badge_key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=100)
    icon: str = Field(..., min_length=1, max_length=50)
    level: str = Field(..., max_length=20)
    trigger_type: TriggerType
    trigger_value: int = Field(..., gt=0)
    # Required for kpi_completions; must be NULL for level; either for streak.
    # Enforced in service.
    kpi_key: Optional[UUID] = None

    @validator("badge_key")
    def normalize_key(cls, value: str) -> str:
        return value.strip()

    @validator("level")
    def validate_level(cls, value: str) -> str:
        v = value.strip().lower()
        if v not in LEVEL_VALUES:
            raise ValueError(f"level must be one of {sorted(LEVEL_VALUES)}")
        return v


class BadgeUpdateRequest(BaseModel):
    # badge_key is the stable identifier — not editable.
    label: Optional[str] = Field(default=None, min_length=1, max_length=100)
    icon: Optional[str] = Field(default=None, min_length=1, max_length=50)
    level: Optional[str] = Field(default=None, max_length=20)
    trigger_type: Optional[TriggerType] = None
    trigger_value: Optional[int] = Field(default=None, gt=0)
    kpi_key: Optional[UUID] = None
    # Pass `null` for kpi_key when promoting a per-KPI badge to global;
    # because Pydantic can't distinguish "field absent" from "field set to
    # null" with this shape, kpi_key edits always overwrite — see service.
    clear_kpi_key: Optional[bool] = Field(
        default=None,
        description=(
            "Set true to explicitly clear kpi_key (NULL). "
            "Otherwise pass kpi_key to set it; omit both to leave unchanged."
        ),
    )
    is_active: Optional[bool] = None

    @validator("level")
    def validate_level(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        v = value.strip().lower()
        if v not in LEVEL_VALUES:
            raise ValueError(f"level must be one of {sorted(LEVEL_VALUES)}")
        return v


class BadgeResponse(BaseModel):
    id: UUID
    badge_key: str
    label: str
    icon: str
    level: str
    trigger_type: str
    trigger_value: int
    kpi_key: Optional[UUID]
    is_active: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime


class BadgeListResponse(BaseModel):
    items: list[BadgeResponse]
    total: int
    skip: int
    limit: int
