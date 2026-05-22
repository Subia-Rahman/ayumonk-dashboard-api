"""Validator unit tests — no DB needed.

Covers the rules enforced by config_service.app.services.cxo_metrics.
validate_mapping_payload, which is run BEFORE any DB write.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.schemas.cxo_metrics import (
    CxoMappingUpdateRequest,
    KpiMappingItem,
    SignalMappingItem,
)
from config_service.app.services.cxo_metrics import validate_mapping_payload


COMPANY = uuid4()
KPI_A = uuid4()
KPI_B = uuid4()


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_weighted_avg_sums_to_one():
    payload = CxoMappingUpdateRequest(
        company_id=COMPANY,
        kpi_mappings=[
            KpiMappingItem(kpi_key=KPI_A, weight=Decimal("0.600")),
            KpiMappingItem(kpi_key=KPI_B, weight=Decimal("0.400")),
        ],
    )
    weight_sum = validate_mapping_payload(
        formula_type="WEIGHTED_AVG", payload=payload
    )
    assert weight_sum == Decimal("1.000")


def test_deficit_sum_accepts_any_weights_with_thresholds():
    payload = CxoMappingUpdateRequest(
        company_id=COMPANY,
        kpi_mappings=[
            KpiMappingItem(
                kpi_key=KPI_A, weight=Decimal("1.200"), threshold=Decimal("3.0")
            ),
            KpiMappingItem(
                kpi_key=KPI_B, weight=Decimal("0.800"), threshold=Decimal("3.0")
            ),
        ],
    )
    validate_mapping_payload(formula_type="DEFICIT_SUM", payload=payload)


def test_composite_sums_to_one():
    payload = CxoMappingUpdateRequest(
        company_id=COMPANY,
        signal_mappings=[
            SignalMappingItem(signal_code="WELLNESS_INDEX", weight=Decimal("0.600")),
            SignalMappingItem(signal_code="FORM_RATE_90D", weight=Decimal("0.400")),
        ],
    )
    weight_sum = validate_mapping_payload(formula_type="COMPOSITE", payload=payload)
    assert weight_sum == Decimal("1.000")


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_weighted_avg_rejects_sum_below_one():
    payload = CxoMappingUpdateRequest(
        company_id=COMPANY,
        kpi_mappings=[
            KpiMappingItem(kpi_key=KPI_A, weight=Decimal("0.500")),
            KpiMappingItem(kpi_key=KPI_B, weight=Decimal("0.450")),
        ],
    )
    with pytest.raises(BusinessException) as exc:
        validate_mapping_payload(formula_type="WEIGHTED_AVG", payload=payload)
    assert "must sum to 1.000" in exc.value.message


def test_weighted_avg_rejects_threshold():
    payload = CxoMappingUpdateRequest(
        company_id=COMPANY,
        kpi_mappings=[
            KpiMappingItem(
                kpi_key=KPI_A, weight=Decimal("0.500"), threshold=Decimal("2.0")
            ),
            KpiMappingItem(kpi_key=KPI_B, weight=Decimal("0.500")),
        ],
    )
    with pytest.raises(BusinessException) as exc:
        validate_mapping_payload(formula_type="WEIGHTED_AVG", payload=payload)
    assert "threshold" in exc.value.message


def test_deficit_sum_rejects_missing_threshold():
    payload = CxoMappingUpdateRequest(
        company_id=COMPANY,
        kpi_mappings=[
            KpiMappingItem(kpi_key=KPI_A, weight=Decimal("1.200")),
        ],
    )
    with pytest.raises(BusinessException) as exc:
        validate_mapping_payload(formula_type="DEFICIT_SUM", payload=payload)
    assert "threshold" in exc.value.message


def test_composite_rejects_kpi_mappings():
    payload = CxoMappingUpdateRequest(
        company_id=COMPANY,
        kpi_mappings=[
            KpiMappingItem(kpi_key=KPI_A, weight=Decimal("0.500")),
        ],
        signal_mappings=[
            SignalMappingItem(signal_code="WELLNESS_INDEX", weight=Decimal("1.000")),
        ],
    )
    with pytest.raises(BusinessException) as exc:
        validate_mapping_payload(formula_type="COMPOSITE", payload=payload)
    assert "kpi_mappings" in exc.value.message


def test_duplicate_kpi_key_rejected_at_schema_level():
    with pytest.raises(ValueError) as exc:
        CxoMappingUpdateRequest(
            company_id=COMPANY,
            kpi_mappings=[
                KpiMappingItem(kpi_key=KPI_A, weight=Decimal("0.500")),
                KpiMappingItem(kpi_key=KPI_A, weight=Decimal("0.500")),
            ],
        )
    assert "Duplicate kpi_key" in str(exc.value)


def test_duplicate_signal_code_rejected_at_schema_level():
    with pytest.raises(ValueError) as exc:
        CxoMappingUpdateRequest(
            company_id=COMPANY,
            signal_mappings=[
                SignalMappingItem(signal_code="WELLNESS_INDEX", weight=Decimal("0.500")),
                SignalMappingItem(signal_code="WELLNESS_INDEX", weight=Decimal("0.500")),
            ],
        )
    assert "Duplicate signal_code" in str(exc.value)
