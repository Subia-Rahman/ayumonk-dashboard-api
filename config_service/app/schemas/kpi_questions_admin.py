from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator


class KPIScoringOptionRequest(BaseModel):
    option_number: int = Field(..., ge=1)
    option_text: str = Field(..., min_length=1, max_length=255)
    score: int = Field(..., ge=0)


class KPIQuestionCreateRequest(BaseModel):
    company_id: UUID
    theme_key: UUID
    kpi_key: UUID
    question_code: str = Field(..., min_length=1, max_length=50)
    question_text: str = Field(..., min_length=1, max_length=500)
    reverse_code: bool = False
    options: List[KPIScoringOptionRequest] = Field(..., min_items=5)

    @validator("options")
    def validate_option_numbers(cls, options: List[KPIScoringOptionRequest]):
        numbers = [opt.option_number for opt in options]
        if len(set(numbers)) != len(numbers):
            raise ValueError("option_number values must be unique")
        return options


class KPIQuestionUpdateRequest(BaseModel):
    theme_key: Optional[UUID] = None
    kpi_key: Optional[UUID] = None
    question_code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    question_text: Optional[str] = Field(default=None, min_length=1, max_length=500)
    reverse_code: Optional[bool] = None
    options: Optional[List[KPIScoringOptionRequest]] = None

    @validator("options")
    def validate_option_numbers(cls, options: Optional[List[KPIScoringOptionRequest]]):
        if options is None:
            return options
        if len(options) < 5:
            raise ValueError("At least 5 scoring options are required")
        numbers = [opt.option_number for opt in options]
        if len(set(numbers)) != len(numbers):
            raise ValueError("option_number values must be unique")
        return options


class KPIScoringOptionResponse(BaseModel):
    option_number: int
    option_text: str
    score: int


class KPIQuestionResponse(BaseModel):
    id: UUID
    company_id: UUID | None = None
    theme_key: UUID
    kpi_key: UUID
    question_code: str
    question_text: str
    reverse_code: bool
    is_active: bool
    options: List[KPIScoringOptionResponse]

    model_config = {"from_attributes": True}


class KPIQuestionListResponse(BaseModel):
    items: List[KPIQuestionResponse]
    total: int
    skip: int
    limit: int
