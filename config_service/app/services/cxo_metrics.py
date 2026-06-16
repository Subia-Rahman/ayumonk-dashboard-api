from __future__ import annotations
"""CXO metric configuration service — validation, snapshots, engagement batch.

Split intentionally from cxo_seeder.py: the seeder owns the "what are the
default rows" decision and is called from POST /reset, while this module owns
the rules that apply to every write (validation, audit snapshotting) plus the
single-roundtrip engagement batch used by the dashboard endpoint.
"""

from decimal import Decimal
from typing import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.cxo_metrics import (
    CxoMetricKpiMapping,
    CxoMetricMaster,
    CxoMetricSignalMapping,
)
from config_service.app.models.kpi import KPI
from config_service.app.schemas.cxo_metrics import (
    CxoMappingUpdateRequest,
    KpiMappingItem,
    SignalMappingItem,
)


# Weights must sum to 1.000 within this tolerance for WEIGHTED_AVG / COMPOSITE.
WEIGHT_SUM_TOLERANCE = Decimal("0.001")
TARGET_WEIGHT_SUM = Decimal("1.000")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _sum_weights(items: Iterable) -> Decimal:
    total = Decimal("0")
    for item in items:
        total += Decimal(str(item.weight))
    return total


def validate_mapping_payload(
    *,
    formula_type: str,
    payload: CxoMappingUpdateRequest,
) -> Decimal:
    """Raise BusinessException unless the payload conforms to the metric's
    formula_type rules. Returns the relevant weight_sum (for echoing back in
    the response).
    """

    if formula_type == "WEIGHTED_AVG":
        if not payload.kpi_mappings:
            raise BusinessException(
                message="WEIGHTED_AVG metric requires at least one kpi_mapping",
                status_code=400,
            )
        if payload.signal_mappings:
            raise BusinessException(
                message="WEIGHTED_AVG metric must not include signal_mappings",
                status_code=400,
            )
        for row in payload.kpi_mappings:
            if row.threshold is not None:
                raise BusinessException(
                    message="WEIGHTED_AVG metric: threshold must be null on every kpi_mapping",
                    status_code=400,
                )
        weight_sum = _sum_weights(payload.kpi_mappings)
        if abs(weight_sum - TARGET_WEIGHT_SUM) > WEIGHT_SUM_TOLERANCE:
            raise BusinessException(
                message=(
                    f"WEIGHTED_AVG kpi_mappings must sum to 1.000 (±0.001); got {weight_sum}"
                ),
                status_code=400,
            )
        return weight_sum

    if formula_type == "DEFICIT_SUM":
        if not payload.kpi_mappings:
            raise BusinessException(
                message="DEFICIT_SUM metric requires at least one kpi_mapping",
                status_code=400,
            )
        if payload.signal_mappings:
            raise BusinessException(
                message="DEFICIT_SUM metric must not include signal_mappings",
                status_code=400,
            )
        for row in payload.kpi_mappings:
            if row.threshold is None:
                raise BusinessException(
                    message="DEFICIT_SUM metric: threshold is required on every kpi_mapping",
                    status_code=400,
                )
        return _sum_weights(payload.kpi_mappings)

    if formula_type == "COMPOSITE":
        if payload.kpi_mappings:
            raise BusinessException(
                message="COMPOSITE metric must not include kpi_mappings",
                status_code=400,
            )
        if not payload.signal_mappings:
            raise BusinessException(
                message="COMPOSITE metric requires at least one signal_mapping",
                status_code=400,
            )
        weight_sum = _sum_weights(payload.signal_mappings)
        if abs(weight_sum - TARGET_WEIGHT_SUM) > WEIGHT_SUM_TOLERANCE:
            raise BusinessException(
                message=(
                    f"COMPOSITE signal_mappings must sum to 1.000 (±0.001); got {weight_sum}"
                ),
                status_code=400,
            )
        return weight_sum

    raise BusinessException(
        message=f"Unknown formula_type '{formula_type}'",
        status_code=500,
    )


def validation_rule_text(formula_type: str) -> str:
    return {
        "WEIGHTED_AVG": "WEIGHTED_AVG must sum to 1.0 (±0.001)",
        "DEFICIT_SUM": "DEFICIT_SUM: threshold required on every row; weights >= 0",
        "COMPOSITE": "COMPOSITE signal weights must sum to 1.0 (±0.001)",
    }.get(formula_type, "unknown")


async def assert_kpi_keys_belong_to_company(
    db: AsyncSession,
    *,
    company_id: UUID,
    kpi_keys: list[UUID],
) -> None:
    if not kpi_keys:
        return
    stmt = select(KPI.kpi_key).where(
        KPI.kpi_key.in_(kpi_keys),
        KPI.company_id == company_id,
        KPI.is_deleted == False,  # noqa: E712
    )
    res = await db.execute(stmt)
    found = {row[0] for row in res.all()}
    missing = [str(k) for k in kpi_keys if k not in found]
    if missing:
        raise BusinessException(
            message=(
                "Some kpi_keys do not exist for this company: "
                + ", ".join(missing)
            ),
            status_code=400,
        )


# ---------------------------------------------------------------------------
# Snapshots — used by the audit log
# ---------------------------------------------------------------------------


def mapping_snapshot(
    *,
    kpi_rows: list[CxoMetricKpiMapping],
    signal_rows: list[CxoMetricSignalMapping],
) -> dict:
    """Build a JSON-serialisable representation of the current mapping. The
    AuditLogService coerces UUID/Decimal/datetime to strings automatically,
    so we can hand raw model attributes through."""
    return {
        "kpi_mappings": [
            {
                "kpi_key": row.kpi_key,
                "weight": row.weight,
                "threshold": row.threshold,
            }
            for row in kpi_rows
        ],
        "signal_mappings": [
            {
                "signal_code": row.signal_code,
                "weight": row.weight,
            }
            for row in signal_rows
        ],
    }


def request_snapshot(payload: CxoMappingUpdateRequest) -> dict:
    return {
        "kpi_mappings": [
            {
                "kpi_key": row.kpi_key,
                "weight": row.weight,
                "threshold": row.threshold,
            }
            for row in payload.kpi_mappings
        ],
        "signal_mappings": [
            {
                "signal_code": row.signal_code,
                "weight": row.weight,
            }
            for row in payload.signal_mappings
        ],
    }


# ---------------------------------------------------------------------------
# Engagement batch — single SQL roundtrip for many users
# ---------------------------------------------------------------------------


async def compute_engagement_batch(
    db: AsyncSession,
    user_ids: list[UUID],
) -> dict[UUID, Decimal | None]:
    """Invoke compute_user_engagement(uuid) for every supplied user id in a
    single SQL statement, using unnest(:ids).

    Returns a dict keyed by user_id. Missing user_ids (or users with no
    Engagement metric configured for their company) map to None, matching the
    PL/pgSQL function's NULL return convention.
    """
    if not user_ids:
        return {}

    # We pass the array as a single bound parameter; asyncpg / psycopg2 both
    # accept Python lists of UUIDs as uuid[]. The cast in the SQL is explicit
    # so the wire-format stays predictable across drivers.
    from sqlalchemy import text as sql_text

    stmt = sql_text(
        """
        SELECT id, compute_user_engagement(id) AS value
        FROM unnest(CAST(:ids AS uuid[])) AS t(id)
        """
    )
    res = await db.execute(stmt, {"ids": user_ids})
    rows = res.all()
    result: dict[UUID, Decimal | None] = {}
    for row in rows:
        user_id, value = row[0], row[1]
        result[user_id] = value
    # Ensure every requested id appears even if unnest didn't yield it.
    for uid in user_ids:
        result.setdefault(uid, None)
    return result


# ---------------------------------------------------------------------------
# Loaders used by the admin GET endpoint
# ---------------------------------------------------------------------------


async def load_metric_and_mapping(
    db: AsyncSession,
    *,
    metric_code: str,
    company_id: UUID,
) -> tuple[CxoMetricMaster, list[tuple[CxoMetricKpiMapping, str]], list[CxoMetricSignalMapping]]:
    """Return (metric, [(kpi_mapping, kpi_display_name)], signal_mappings)."""
    metric_stmt = select(CxoMetricMaster).where(
        CxoMetricMaster.company_id == company_id,
        CxoMetricMaster.metric_code == metric_code,
        CxoMetricMaster.is_active == True,  # noqa: E712
    )
    metric = (await db.execute(metric_stmt)).scalar_one_or_none()
    if metric is None:
        raise BusinessException(
            message=f"Metric '{metric_code}' not found", status_code=404
        )

    kpi_stmt = (
        select(CxoMetricKpiMapping, KPI.display_name)
        .join(KPI, KPI.kpi_key == CxoMetricKpiMapping.kpi_key)
        .where(
            CxoMetricKpiMapping.company_id == company_id,
            CxoMetricKpiMapping.metric_id == metric.id,
            CxoMetricKpiMapping.is_active == True,  # noqa: E712
        )
        .order_by(CxoMetricKpiMapping.weight.desc())
    )
    kpi_rows = [(row[0], row[1]) for row in (await db.execute(kpi_stmt)).all()]

    signal_stmt = (
        select(CxoMetricSignalMapping)
        .where(
            CxoMetricSignalMapping.company_id == company_id,
            CxoMetricSignalMapping.metric_id == metric.id,
            CxoMetricSignalMapping.is_active == True,  # noqa: E712
        )
        .order_by(CxoMetricSignalMapping.weight.desc())
    )
    signal_rows = list((await db.execute(signal_stmt)).scalars().all())

    return metric, kpi_rows, signal_rows
