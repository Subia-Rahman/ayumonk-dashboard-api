from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, root_validator, validator


_TOGGLE_OR_RATING = {"toggle", "rating"}
_REQUIRE_OPTIONS = {"multi", "choice"}


def _clean_options(value):
    """Strip + dedupe option labels; reject empty list."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("options must be a list of strings")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("each option must be a string")
        s = item.strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(s)
    if not cleaned:
        raise ValueError("options cannot be empty")
    return cleaned


class ChallengeKPIMappingRequest(BaseModel):
    kpi_key: UUID
    start_date: date
    end_date: Optional[date] = None

    @validator("end_date")
    def validate_date_range(cls, end_date: Optional[date], values):
        start_date = values.get("start_date")
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date cannot be greater than end_date")
        return end_date


class ChallengeCreateRequest(BaseModel):
    company_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    challenge_type: str = Field(..., min_length=1, max_length=20)
    description: Optional[str] = None
    target_value: Optional[int] = Field(default=None, ge=0)
    xp_reward: int = Field(default=20, ge=0, le=1000)
    icon: Optional[str] = Field(default=None, max_length=50)
    is_daily: bool = True
    options: Optional[list[str]] = None
    kpi_mappings: list[ChallengeKPIMappingRequest] = Field(default_factory=list)

    @validator("name")
    def normalize_name(cls, value: str) -> str:
        return value.strip()

    @validator("challenge_type")
    def normalize_type(cls, value: str) -> str:
        return value.strip()

    @validator("icon")
    def normalize_icon(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip() or None

    @validator("options")
    def normalize_options(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _clean_options(value)

    @root_validator(skip_on_failure=True)
    def apply_type_rules(cls, values):
        # target_value is meaningless for toggle/rating — drop it silently so
        # the admin UI can show the field hidden but the API stays defensive
        # against stale payloads.
        ctype = (values.get("challenge_type") or "").lower()
        if ctype in _TOGGLE_OR_RATING:
            values["target_value"] = None
            values["options"] = None
        elif ctype in _REQUIRE_OPTIONS:
            if not values.get("options"):
                raise ValueError(
                    f"options is required for '{ctype}' challenges"
                )
            if ctype == "choice" and len(values["options"]) < 2:
                raise ValueError("choice challenges need at least 2 options")
        else:
            # counter/timer don't use options
            values["options"] = None
        return values


class ChallengeUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    challenge_type: Optional[str] = Field(default=None, min_length=1, max_length=20)
    description: Optional[str] = None
    target_value: Optional[int] = Field(default=None, ge=0)
    xp_reward: Optional[int] = Field(default=None, ge=0, le=1000)
    icon: Optional[str] = Field(default=None, max_length=50)
    is_daily: Optional[bool] = None
    is_active: Optional[bool] = None
    options: Optional[list[str]] = None

    @validator("name")
    def normalize_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip()

    @validator("challenge_type")
    def normalize_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip()

    @validator("icon")
    def normalize_icon(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip() or None

    @validator("options")
    def normalize_options(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return _clean_options(value)

    @root_validator(skip_on_failure=True)
    def apply_type_rules(cls, values):
        # When the caller is also changing the type, enforce type-vs-fields
        # consistency here (the service layer will re-apply when the type
        # changes via PATCH without a fresh options payload).
        ctype = (values.get("challenge_type") or "")
        if not ctype:
            return values
        ctype = ctype.lower()
        if ctype in _TOGGLE_OR_RATING:
            values["target_value"] = None
            values["options"] = None
        elif ctype in _REQUIRE_OPTIONS:
            if values.get("options") is not None and len(values["options"]) < (2 if ctype == "choice" else 1):
                raise ValueError(f"options too short for '{ctype}' challenges")
        return values


class ChallengeResponse(BaseModel):
    challenge_key: UUID
    company_id: UUID | None = None
    name: str
    challenge_type: str
    description: Optional[str]
    target_value: Optional[int]
    xp_reward: int
    icon: Optional[str]
    is_daily: bool
    is_active: bool
    options: Optional[list[str]] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    kpi_keys: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ChallengeListResponse(BaseModel):
    items: list[ChallengeResponse]
    total: int
    skip: int
    limit: int


class ChallengeKPIMappingResponse(BaseModel):
    id: UUID
    kpi_key: UUID
    start_date: date
    end_date: Optional[date]
    created_at: datetime
    updated_at: datetime


class ChallengeDetailResponse(BaseModel):
    challenge: ChallengeResponse
    kpi_mappings: list[ChallengeKPIMappingResponse]


class KPIChallengeActiveResponse(BaseModel):
    challenge_key: UUID
    name: str
    challenge_type: str
    description: Optional[str]
    target_value: Optional[int]
    xp_reward: int
    icon: Optional[str]
    is_daily: bool
    options: Optional[list[str]] = None
    start_date: date
    end_date: Optional[date]
