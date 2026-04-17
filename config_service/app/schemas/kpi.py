from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator


class KPICreateRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=255)
    theme_key: UUID
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    domain_category: Optional[str] = None
    wi_weight: Optional[float] = 0.10

    @validator("display_name")
    def normalize_name(cls, value: str) -> str:
        return value.strip()

    @validator("end_date")
    def validate_date_range(cls, end_date: Optional[date], values):
        start_date = values.get("start_date")
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date cannot be greater than end_date")
        return end_date


class KPIUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    theme_key: Optional[UUID] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    domain_category: Optional[str] = None
    wi_weight: Optional[float] = None
    is_active: Optional[bool] = None

    @validator("display_name")
    def normalize_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip()

    @validator("end_date")
    def validate_date_range(cls, end_date: Optional[date], values):
        start_date = values.get("start_date")
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date cannot be greater than end_date")
        return end_date


class KPIResponse(BaseModel):
    kpi_key: UUID
    display_name: str
    theme_key: UUID
    start_date: Optional[date]
    end_date: Optional[date]
    domain_category: Optional[str] = None
    wi_weight: Optional[float] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class KPIListResponse(BaseModel):
    items: list[KPIResponse]
    total: int
    skip: int
    limit: int
