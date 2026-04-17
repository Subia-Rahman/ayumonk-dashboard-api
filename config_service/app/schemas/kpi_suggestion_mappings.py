from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator, field_validator


TRIGGER_MODES = {"kpi_risk", "question_score", "both"}


class KPISuggestionMappingCreateRequest(BaseModel):
    kpi_key: UUID
    trigger_mode: str = Field(..., min_length=1, max_length=20)
    risk_level: Optional[str] = None
    question_key: Optional[UUID] = None
    score_threshold_below: Optional[int] = None
    score_threshold_above: Optional[int] = None
    kpi_score_below: Optional[int] = None
    suggestion_id: UUID
    priority: int = Field(default=1, ge=1)
    is_active: bool = True

    @field_validator("trigger_mode")
    @classmethod
    def validate_trigger_mode(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in TRIGGER_MODES:
            raise ValueError("trigger_mode must be one of kpi_risk, question_score, both")
        return value

    @model_validator(mode="after")
    def validate_business_rules(self):
        mode = self.trigger_mode
        if mode == "kpi_risk":
            if not self.risk_level:
                raise ValueError("risk_level is required when trigger_mode is kpi_risk")
            if self.question_key is not None:
                raise ValueError("question_key must be null when trigger_mode is kpi_risk")
            if self.score_threshold_below is not None or self.score_threshold_above is not None:
                raise ValueError("score thresholds must be null when trigger_mode is kpi_risk")
        elif mode == "question_score":
            if self.question_key is None:
                raise ValueError("question_key is required when trigger_mode is question_score")
            if self.score_threshold_below is None and self.score_threshold_above is None:
                raise ValueError("at least one score threshold is required")
            if self.risk_level is not None:
                raise ValueError("risk_level must be null when trigger_mode is question_score")
        elif mode == "both":
            if not self.risk_level:
                raise ValueError("risk_level is required when trigger_mode is both")
            if self.question_key is None:
                raise ValueError("question_key is required when trigger_mode is both")
            if self.score_threshold_below is None and self.score_threshold_above is None:
                raise ValueError("at least one score threshold is required")
        return self


class KPISuggestionMappingUpdateRequest(BaseModel):
    kpi_key: Optional[UUID] = None
    trigger_mode: Optional[str] = Field(default=None, min_length=1, max_length=20)
    risk_level: Optional[str] = None
    question_key: Optional[UUID] = None
    score_threshold_below: Optional[int] = None
    score_threshold_above: Optional[int] = None
    kpi_score_below: Optional[int] = None
    suggestion_id: Optional[UUID] = None
    priority: Optional[int] = Field(default=None, ge=1)
    is_active: Optional[bool] = None

    @field_validator("trigger_mode")
    @classmethod
    def validate_trigger_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().lower()
        if value not in TRIGGER_MODES:
            raise ValueError("trigger_mode must be one of kpi_risk, question_score, both")
        return value

    @model_validator(mode="after")
    def validate_business_rules(self):
        if self.trigger_mode is None:
            return self
        mode = self.trigger_mode
        if mode == "kpi_risk":
            if not self.risk_level:
                raise ValueError("risk_level is required when trigger_mode is kpi_risk")
            if self.question_key is not None:
                raise ValueError("question_key must be null when trigger_mode is kpi_risk")
            if self.score_threshold_below is not None or self.score_threshold_above is not None:
                raise ValueError("score thresholds must be null when trigger_mode is kpi_risk")
        elif mode == "question_score":
            if self.question_key is None:
                raise ValueError("question_key is required when trigger_mode is question_score")
            if self.score_threshold_below is None and self.score_threshold_above is None:
                raise ValueError("at least one score threshold is required")
            if self.risk_level is not None:
                raise ValueError("risk_level must be null when trigger_mode is question_score")
        elif mode == "both":
            if not self.risk_level:
                raise ValueError("risk_level is required when trigger_mode is both")
            if self.question_key is None:
                raise ValueError("question_key is required when trigger_mode is both")
            if self.score_threshold_below is None and self.score_threshold_above is None:
                raise ValueError("at least one score threshold is required")
        return self


class KPISuggestionMappingResponse(BaseModel):
    id: UUID
    kpi_key: UUID
    trigger_mode: str
    risk_level: Optional[str]
    question_key: Optional[UUID]
    score_threshold_below: Optional[int]
    score_threshold_above: Optional[int]
    kpi_score_below: Optional[int]
    suggestion_id: UUID
    priority: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KPISuggestionMappingListResponse(BaseModel):
    items: list[KPISuggestionMappingResponse]
    total: int
    skip: int
    limit: int
