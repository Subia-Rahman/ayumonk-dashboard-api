from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Wellness dimension schemas
# ---------------------------------------------------------------------------


def _slugify_dimension_key(value: str) -> str:
    """Normalize a dimension_key: trim, lowercase, replace whitespace runs with
    underscores. Mirrors the validation rule documented on POST /dimensions."""
    cleaned = (value or "").strip().lower()
    return "_".join(cleaned.split())


class WellnessDimensionCreateRequest(BaseModel):
    dimension_key: str = Field(..., min_length=1, max_length=50)
    dimension_label: str = Field(..., min_length=1, max_length=100)
    display_order: int = Field(default=1)
    is_active: bool = True

    @field_validator("dimension_key")
    @classmethod
    def normalize_dimension_key(cls, value: str) -> str:
        return _slugify_dimension_key(value)

    @field_validator("dimension_label")
    @classmethod
    def trim_label(cls, value: str) -> str:
        return value.strip()


class WellnessDimensionUpdateRequest(BaseModel):
    """PATCH-style update. `dimension_key` is intentionally absent — it is
    immutable after creation."""

    dimension_label: Optional[str] = Field(default=None, min_length=1, max_length=100)
    display_order: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("dimension_label")
    @classmethod
    def trim_label(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip()


class WellnessDimensionResponse(BaseModel):
    id: int
    company_id: UUID
    dimension_key: str
    dimension_label: str
    display_order: int
    is_active: bool
    kpi_count: int = 0
    created_at: datetime
    updated_at: datetime
    created_by: Optional[int] = None
    updated_by: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class WellnessDimensionListResponse(BaseModel):
    items: list[WellnessDimensionResponse]


# ---------------------------------------------------------------------------
# Dimension-KPI mapping schemas
# ---------------------------------------------------------------------------


class DimensionKpiMappingCreateRequest(BaseModel):
    kpi_key: UUID
    weight: Decimal = Field(default=Decimal("1.00"), max_digits=4, decimal_places=2)
    display_order: int = Field(default=1)
    is_active: bool = True


class DimensionKpiMappingUpdateRequest(BaseModel):
    """PATCH-style update. `kpi_key` and `dimension_id` are intentionally absent
    — they are immutable on a mapping row."""

    weight: Optional[Decimal] = Field(default=None, max_digits=4, decimal_places=2)
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class DimensionKpiMappingResponse(BaseModel):
    id: int
    company_id: UUID
    dimension_id: int
    kpi_key: UUID
    display_name: Optional[str] = None
    wi_weight: Optional[Decimal] = None
    weight: Decimal
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[int] = None
    updated_by: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class DimensionKpiMappingListResponse(BaseModel):
    items: list[DimensionKpiMappingResponse]
