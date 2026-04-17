from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator


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
    name: str = Field(..., min_length=1, max_length=255)
    challenge_type: str = Field(..., min_length=1, max_length=20)
    description: Optional[str] = None
    target_value: Optional[int] = Field(default=None, ge=0)
    xp_reward: int = Field(default=20, ge=0, le=1000)
    icon: Optional[str] = Field(default=None, max_length=50)
    is_daily: bool = True
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


class ChallengeUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    challenge_type: Optional[str] = Field(default=None, min_length=1, max_length=20)
    description: Optional[str] = None
    target_value: Optional[int] = Field(default=None, ge=0)
    xp_reward: Optional[int] = Field(default=None, ge=0, le=1000)
    icon: Optional[str] = Field(default=None, max_length=50)
    is_daily: Optional[bool] = None
    is_active: Optional[bool] = None

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


class ChallengeResponse(BaseModel):
    challenge_key: UUID
    name: str
    challenge_type: str
    description: Optional[str]
    target_value: Optional[int]
    xp_reward: int
    icon: Optional[str]
    is_daily: bool
    is_active: bool
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
    start_date: date
    end_date: Optional[date]
