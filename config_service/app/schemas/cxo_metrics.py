from __future__ import annotations
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
    description: Optional[str] = None
    is_active: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[int] = None
    updated_by: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class CxoMetricListResponse(BaseModel):
    items: list[CxoMetricRead]


# ---------------------------------------------------------------------------
# CXO metric master CRUD payloads
# ---------------------------------------------------------------------------


class CxoMetricCreate(BaseModel):
    company_id: UUID
    metric_code: str = Field(min_length=1, max_length=30)
    display_name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = None
    is_active: bool = True


class CxoMetricUpdate(BaseModel):
    """PATCH-style: only the supplied fields are applied. `company_id` and
    `metric_code` are intentionally absent — they're immutable because the
    KPI mapping rows reference `metric_id` and `(company_id, metric_id)`."""
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# CXO KPI mapping CRUD schemas
# ---------------------------------------------------------------------------


class CxoKpiMappingItem(BaseModel):
    """One KPI's contribution to a metric. Used inside the create request."""
    kpi_key: UUID
    weight: Decimal = Field(ge=0, max_digits=4, decimal_places=3)


class CxoKpiMappingCreateRequest(BaseModel):
    company_id: UUID
    metric_id: UUID
    kpi_mappings: list[CxoKpiMappingItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _no_intra_request_dupes(self):
        keys = [item.kpi_key for item in self.kpi_mappings]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate kpi_key in kpi_mappings")
        return self


class CxoKpiMappingUpdateRequest(BaseModel):
    """Update the weight on a single mapping row."""
    weight: Decimal = Field(ge=0, max_digits=4, decimal_places=3)


class CxoKpiMappingStatusUpdate(BaseModel):
    is_active: bool


class CxoKpiMappingRead(BaseModel):
    id: UUID
    company_id: UUID
    metric_id: UUID
    kpi_key: UUID
    kpi_name: Optional[str] = None
    weight: Decimal
    is_active: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime
    created_by: Optional[int] = None
    updated_by: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class CxoKpiMappingListResponse(BaseModel):
    items: list[CxoKpiMappingRead]


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
# HR CXO metrics endpoint (GET /api/v1/hr/cxo-metrics)
# ---------------------------------------------------------------------------


class HrCxoBucket(BaseModel):
    """One aggregation bucket (department name or age band)."""
    label: str
    value: Decimal


class HrCxoMetricResponse(BaseModel):
    """Combined response: both breakdowns for a single CXO metric."""
    metric: str
    by_department: list[HrCxoBucket]
    by_age_band: list[HrCxoBucket]


class HrCxoMetricDefinition(BaseModel):
    """One entry in the definitions list — drives the frontend toggle buttons."""
    key: str
    label: str
