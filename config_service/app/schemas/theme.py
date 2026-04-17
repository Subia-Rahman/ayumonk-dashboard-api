from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator


class ThemeCreateRequest(BaseModel):
    theme_display_name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    duration_days: int | None = None
    target_audience: str | None = None

    @validator("theme_display_name")
    def normalize_name(cls, value: str) -> str:
        return value.strip()


class ThemeUpdateRequest(BaseModel):
    theme_display_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    duration_days: int | None = None
    target_audience: str | None = None
    is_active: Optional[bool] = None

    @validator("theme_display_name")
    def normalize_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip()


class ThemeResponse(BaseModel):
    theme_key: UUID
    theme_display_name: str
    description: str | None = None
    duration_days: int | None = None
    target_audience: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ThemeListResponse(BaseModel):
    items: list[ThemeResponse]
    total: int
    skip: int
    limit: int
