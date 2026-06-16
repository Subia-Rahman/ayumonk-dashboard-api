from __future__ import annotations
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


SUGGESTION_TYPES = {"aahar", "vihar", "aushadh"}
DOSHA_TYPES = {"vata", "pitta", "kapha", "all"}
DIFFICULTY_LEVELS = {"easy", "moderate", "advanced"}


class SuggestionCreateRequest(BaseModel):
    suggestion_type: str = Field(..., min_length=1, max_length=20)
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    url: Optional[str] = Field(default=None, max_length=1024)
    dosha_type: str = Field(default="all", max_length=20)
    difficulty: Optional[str] = Field(default=None, max_length=20)
    duration_mins: Optional[int] = Field(default=None, ge=0)
    is_active: bool = True

    @field_validator("suggestion_type")
    @classmethod
    def validate_suggestion_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in SUGGESTION_TYPES:
            raise ValueError("suggestion_type must be one of aahar, vihar, aushadh")
        return value

    @field_validator("dosha_type")
    @classmethod
    def validate_dosha_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in DOSHA_TYPES:
            raise ValueError("dosha_type must be one of vata, pitta, kapha, all")
        return value

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in DIFFICULTY_LEVELS:
            raise ValueError("difficulty must be one of easy, moderate, advanced")
        return value


class SuggestionUpdateRequest(BaseModel):
    suggestion_type: Optional[str] = Field(default=None, min_length=1, max_length=20)
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    url: Optional[str] = Field(default=None, max_length=1024)
    dosha_type: Optional[str] = Field(default=None, max_length=20)
    difficulty: Optional[str] = Field(default=None, max_length=20)
    duration_mins: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None

    @field_validator("suggestion_type")
    @classmethod
    def validate_suggestion_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in SUGGESTION_TYPES:
            raise ValueError("suggestion_type must be one of aahar, vihar, aushadh")
        return value

    @field_validator("dosha_type")
    @classmethod
    def validate_dosha_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in DOSHA_TYPES:
            raise ValueError("dosha_type must be one of vata, pitta, kapha, all")
        return value

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in DIFFICULTY_LEVELS:
            raise ValueError("difficulty must be one of easy, moderate, advanced")
        return value


class SuggestionResponse(BaseModel):
    id: UUID
    suggestion_type: str
    title: str
    description: Optional[str]
    url: Optional[str]
    dosha_type: str
    difficulty: Optional[str]
    duration_mins: Optional[int]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SuggestionListResponse(BaseModel):
    items: list[SuggestionResponse]
    total: int
    skip: int
    limit: int
