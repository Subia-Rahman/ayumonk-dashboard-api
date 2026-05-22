from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Controlled vocabulary for composite signals. Must match
# ck_signal_code on cxo_metric_signal_mapping and the branches in
# compute_user_engagement(uuid).
SignalCode = Literal[
    "WELLNESS_INDEX",
    "CHALLENGE_RATE_30D",
    "FORM_RATE_90D",
    "MOOD_AVG",
]
SIGNAL_CODES: list[SignalCode] = [
    "WELLNESS_INDEX",
    "CHALLENGE_RATE_30D",
    "FORM_RATE_90D",
    "MOOD_AVG",
]
SIGNAL_DISPLAY_NAMES: dict[SignalCode, str] = {
    "WELLNESS_INDEX": "Wellness Index",
    "CHALLENGE_RATE_30D": "Challenge completion (30d)",
    "FORM_RATE_90D": "Form response rate (90d)",
    "MOOD_AVG": "Average mood",
}


# ---------------------------------------------------------------------------
# Request items
# ---------------------------------------------------------------------------


class KpiMappingItem(BaseModel):
    kpi_key: UUID
    weight: Decimal = Field(ge=0, decimal_places=3)
    threshold: Decimal | None = Field(
        default=None, ge=0, le=5, decimal_places=2
    )


class SignalMappingItem(BaseModel):
    signal_code: SignalCode
    weight: Decimal = Field(ge=0, le=1, decimal_places=3)


class CxoMappingUpdateRequest(BaseModel):
    company_id: UUID
    kpi_mappings: list[KpiMappingItem] = []
    signal_mappings: list[SignalMappingItem] = []

    @model_validator(mode="after")
    def _no_intra_request_dupes(self):
        kpi_keys = [item.kpi_key for item in self.kpi_mappings]
        if len(kpi_keys) != len(set(kpi_keys)):
            raise ValueError("Duplicate kpi_key in kpi_mappings")
        signals = [item.signal_code for item in self.signal_mappings]
        if len(signals) != len(set(signals)):
            raise ValueError("Duplicate signal_code in signal_mappings")
        return self


class CxoMetricResetRequest(BaseModel):
    company_id: UUID


# ---------------------------------------------------------------------------
# Response items
# ---------------------------------------------------------------------------


class MetricSummary(BaseModel):
    metric_code: str
    display_name: str
    formula_type: str
    baseline: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)


class CxoMetricRead(BaseModel):
    id: UUID
    company_id: UUID
    metric_code: str
    display_name: str
    unit: str
    scale_min: Decimal | None = None
    scale_max: Decimal | None = None
    baseline: Decimal | None = None
    formula_type: str
    description: Optional[str] = None
    methodology_ref: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Form payload for POST /admin/cxo-metrics. Mirrors the cxo_metric_master
# column types/constraints — keep the bounds in sync with the table DDL.
class CxoMetricMasterCreate(BaseModel):
    company_id: UUID
    metric_code: str = Field(min_length=1, max_length=30)
    display_name: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=20)
    scale_min: Decimal = Field(default=Decimal("0"), max_digits=6, decimal_places=2)
    scale_max: Decimal = Field(default=Decimal("100"), max_digits=6, decimal_places=2)
    baseline: Decimal | None = Field(default=None, max_digits=6, decimal_places=2)
    formula_type: Literal["WEIGHTED_AVG", "DEFICIT_SUM", "COMPOSITE"]
    description: Optional[str] = None
    methodology_ref: Optional[str] = None


# PATCH-style payload for PUT /admin/cxo-metrics/{metric_code}. Every field is
# optional — only the keys actually present in the request body are applied
# (via `model_dump(exclude_unset=True)`). `metric_code`, `company_id`, and
# `formula_type` are intentionally absent: rename/move/recategorize requires
# delete + recreate so mappings stay consistent.
class CxoMetricMasterUpdate(BaseModel):
    company_id: UUID
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    unit: Optional[str] = Field(default=None, min_length=1, max_length=20)
    scale_min: Optional[Decimal] = Field(default=None, max_digits=6, decimal_places=2)
    scale_max: Optional[Decimal] = Field(default=None, max_digits=6, decimal_places=2)
    baseline: Optional[Decimal] = Field(default=None, max_digits=6, decimal_places=2)
    description: Optional[str] = None
    methodology_ref: Optional[str] = None


class CxoMetricListResponse(BaseModel):
    items: list[CxoMetricRead]


class KpiMappingResponse(BaseModel):
    kpi_key: UUID
    kpi_name: str
    weight: Decimal
    threshold: Decimal | None = None


class SignalMappingResponse(BaseModel):
    signal_code: SignalCode
    weight: Decimal


class MappingValidationInfo(BaseModel):
    weight_sum: Decimal
    is_valid: bool
    rule: str


class CxoMappingResponse(BaseModel):
    metric: MetricSummary
    kpi_mappings: list[KpiMappingResponse]
    signal_mappings: list[SignalMappingResponse]
    validation: MappingValidationInfo


# ---------------------------------------------------------------------------
# Options endpoint
# ---------------------------------------------------------------------------


class KpiOption(BaseModel):
    kpi_key: UUID
    display_name: str


class SignalOption(BaseModel):
    signal_code: SignalCode
    display_name: str


class CxoOptionsResponse(BaseModel):
    kpis: list[KpiOption]
    signals: list[SignalOption]


# ---------------------------------------------------------------------------
# Seeder result
# ---------------------------------------------------------------------------


class SeedResult(BaseModel):
    seeded: list[str] = []
    skipped_kpis: list[str] = []
    errors: list[str] = []


# ---------------------------------------------------------------------------
# Dashboard endpoint
# ---------------------------------------------------------------------------


class CxoBucket(BaseModel):
    label: str
    value: Decimal
    cohortSize: int  # noqa: N815 — wire format matches existing dashboard responses.


class CxoMeta(BaseModel):
    metric: str
    breakdown: str
    cohortSize: int  # noqa: N815
    kAnonymityFloor: int  # noqa: N815
    updatedAt: datetime  # noqa: N815
    suppressedBuckets: int  # noqa: N815


class CxoByDimensionResponse(BaseModel):
    data: list[CxoBucket]
    meta: CxoMeta
