"""Default CXO mapping seeder.

Inserts (or updates, on conflict) the platform-default KPI / signal weights
for a given company. Used by the POST /cxo-metrics/{metric_code}/reset
endpoint and by tenant-bootstrap flows.

Default figures are sourced from the CXO metrics methodology document — see
docs/README-CXO-METRICS.md for context.

TODO(schema-issue-2): KPI matching is done by case-insensitive trimmed
display_name (`func.lower(func.trim(...))`). The kpis table has no controlled
vocabulary or kpi_code yet; if a customer renames "Sleep" to "Sleep Quality"
the corresponding row will be silently skipped (logged + reported in
SeedResult.skipped_kpis). Follow-up: introduce a kpis.kpi_code column with a
CHECK constraint, then key the seed off that.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.services.audit_log_service import AuditLogService
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.models.cxo_metrics import (
    CxoMetricKpiMapping,
    CxoMetricMaster,
    CxoMetricSignalMapping,
)
from config_service.app.models.kpi import KPI
from config_service.app.schemas.cxo_metrics import SeedResult


logger = get_file_logger(name="cxo_seeder", prefix="cxo_seeder")


# ---------------------------------------------------------------------------
# Default-mapping figures (Productivity / Absenteeism / Engagement)
# Values are exact figures from the CXO metrics methodology document.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _KpiDefault:
    kpi_name: str
    weight: Decimal
    threshold: Decimal | None = None


@dataclass(frozen=True)
class _SignalDefault:
    signal_code: str
    weight: Decimal


PRODUCTIVITY_DEFAULTS: tuple[_KpiDefault, ...] = (
    _KpiDefault("Stress",    Decimal("0.300")),
    _KpiDefault("Sleep",     Decimal("0.250")),
    _KpiDefault("Energy",    Decimal("0.200")),
    _KpiDefault("Pain",      Decimal("0.100")),
    _KpiDefault("Activity",  Decimal("0.100")),
    _KpiDefault("Digestion", Decimal("0.050")),
)

ABSENTEEISM_DEFAULTS: tuple[_KpiDefault, ...] = (
    _KpiDefault("Sleep",     Decimal("1.200"), Decimal("3.0")),
    _KpiDefault("Stress",    Decimal("0.800"), Decimal("3.0")),
    _KpiDefault("Pain",      Decimal("0.600"), Decimal("3.0")),
    _KpiDefault("Energy",    Decimal("0.400"), Decimal("3.0")),
    _KpiDefault("Digestion", Decimal("0.300"), Decimal("3.0")),
)

ENGAGEMENT_SIGNAL_DEFAULTS: tuple[_SignalDefault, ...] = (
    _SignalDefault("WELLNESS_INDEX",     Decimal("0.400")),
    _SignalDefault("CHALLENGE_RATE_30D", Decimal("0.300")),
    _SignalDefault("FORM_RATE_90D",      Decimal("0.200")),
    _SignalDefault("MOOD_AVG",           Decimal("0.100")),
)


ALL_METRIC_CODES: tuple[str, ...] = ("PRODUCTIVITY", "ABSENTEEISM", "ENGAGEMENT")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def seed_default_cxo_mappings(
    db: AsyncSession,
    company_id: UUID,
    actor_user_id: int,
    metric_codes: list[str] | None = None,
) -> SeedResult:
    """Seed default mappings for the given company. Idempotent — re-running
    is a no-op except for an audit log entry per metric. All inserts for one
    invocation run inside a single nested transaction so a downstream failure
    rolls them all back.

    Args:
        db: An async SQLAlchemy session. The caller owns the outer
            transaction; this function uses begin_nested() so the caller's
            commit/rollback semantics are preserved.
        company_id: Target tenant.
        actor_user_id: created_by / updated_by + audit log user_id.
        metric_codes: When None, seeds all three metrics. Subset accepted.
    """
    codes = list(metric_codes) if metric_codes else list(ALL_METRIC_CODES)
    unknown = [c for c in codes if c not in ALL_METRIC_CODES]
    if unknown:
        raise ValueError(f"Unknown metric_codes: {unknown}")

    db.info["user_id"] = actor_user_id

    result = SeedResult()

    # Resolve every needed KPI in one query (case-insensitive trim).
    kpi_name_to_key = await _resolve_company_kpis(db, company_id=company_id)

    # Cache the metric master rows (id + formula_type) for this company.
    masters = await _load_metric_masters(db, company_id=company_id)
    code_to_master = {m.metric_code: m for m in masters}

    async with db.begin_nested():
        for code in codes:
            master = code_to_master.get(code)
            if master is None:
                msg = f"cxo_metric_master row missing for code '{code}'"
                result.errors.append(msg)
                logger.warning(msg)
                continue

            try:
                if code == "PRODUCTIVITY":
                    skipped = await _upsert_kpi_defaults(
                        db,
                        company_id=company_id,
                        metric_id=master.id,
                        actor_user_id=actor_user_id,
                        defaults=PRODUCTIVITY_DEFAULTS,
                        kpi_name_to_key=kpi_name_to_key,
                    )
                    result.skipped_kpis.extend(skipped)
                elif code == "ABSENTEEISM":
                    skipped = await _upsert_kpi_defaults(
                        db,
                        company_id=company_id,
                        metric_id=master.id,
                        actor_user_id=actor_user_id,
                        defaults=ABSENTEEISM_DEFAULTS,
                        kpi_name_to_key=kpi_name_to_key,
                    )
                    result.skipped_kpis.extend(skipped)
                elif code == "ENGAGEMENT":
                    await _upsert_signal_defaults(
                        db,
                        company_id=company_id,
                        metric_id=master.id,
                        actor_user_id=actor_user_id,
                        defaults=ENGAGEMENT_SIGNAL_DEFAULTS,
                    )
                result.seeded.append(code)

                # Audit per metric (action: SEED_CXO_MAPPING). Use queue()
                # because we own the surrounding begin_nested() transaction;
                # log() would commit and close it, breaking the context
                # manager on exit.
                AuditLogService(db).queue(
                    user_id=actor_user_id,
                    tenant_id=company_id,
                    action="SEED_CXO_MAPPING",
                    entity="cxo_metric_kpi_mapping" if code != "ENGAGEMENT" else "cxo_metric_signal_mapping",
                    old_value=None,
                    new_value={
                        "metric_code": code,
                        "company_id": company_id,
                    },
                )
            except Exception as exc:  # pragma: no cover — defensive
                logger.exception(
                    "ERROR | seed_default_cxo_mappings | metric=%s | company_id=%s",
                    code,
                    company_id,
                )
                result.errors.append(f"{code}: {exc}")
                raise

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_metric_masters(
    db: AsyncSession, *, company_id: UUID
) -> list[CxoMetricMaster]:
    stmt = select(CxoMetricMaster).where(
        CxoMetricMaster.company_id == company_id,
        CxoMetricMaster.is_active == True,  # noqa: E712
        CxoMetricMaster.metric_code.in_(ALL_METRIC_CODES),
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def _resolve_company_kpis(
    db: AsyncSession,
    *,
    company_id: UUID,
) -> dict[str, UUID]:
    """Case-insensitive trimmed display_name -> kpi_key for the given company.
    Returns lowercase trimmed names as keys."""
    stmt = select(KPI.kpi_key, KPI.display_name).where(
        KPI.company_id == company_id,
        KPI.is_active == True,  # noqa: E712
        KPI.is_deleted == False,  # noqa: E712
    )
    res = await db.execute(stmt)
    out: dict[str, UUID] = {}
    for kpi_key, display_name in res.all():
        if display_name is None:
            continue
        out[display_name.strip().lower()] = kpi_key
    return out


async def _upsert_kpi_defaults(
    db: AsyncSession,
    *,
    company_id: UUID,
    metric_id: UUID,
    actor_user_id: int,
    defaults: Iterable[_KpiDefault],
    kpi_name_to_key: dict[str, UUID],
) -> list[str]:
    """Insert / update mappings for every default. Returns the list of KPI
    names that couldn't be matched to a kpi_key (and were therefore skipped).
    """
    skipped: list[str] = []
    rows: list[dict] = []
    for default in defaults:
        kpi_key = kpi_name_to_key.get(default.kpi_name.strip().lower())
        if kpi_key is None:
            logger.warning(
                "WARN | seed_default_cxo_mappings | missing_kpi | company_id=%s | metric_id=%s | kpi_name=%s",
                company_id,
                metric_id,
                default.kpi_name,
            )
            skipped.append(default.kpi_name)
            continue
        # Explicit id / created_at / updated_at because pg_insert(Model).values()
        # does NOT fire Python-side ORM defaults, and AuditMixin's defaults
        # are Python-side only. If the table was created by
        # Base.metadata.create_all (rather than cxo_metrics_up.sql) there are
        # no server defaults either, so we have to supply them ourselves.
        rows.append(
            {
                "id": uuid.uuid4(),
                "company_id": company_id,
                "metric_id": metric_id,
                "kpi_key": kpi_key,
                "weight": default.weight,
                "threshold": default.threshold,
                "is_active": True,
                "is_deleted": False,
                "created_at": func.now(),
                "updated_at": func.now(),
                "created_by": actor_user_id,
                "updated_by": actor_user_id,
            }
        )

    if not rows:
        return skipped

    stmt = pg_insert(CxoMetricKpiMapping).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_company_metric_kpi",
        set_={
            "weight": stmt.excluded.weight,
            "threshold": stmt.excluded.threshold,
            "is_active": True,
            "is_deleted": False,
            "updated_at": func.now(),
            "updated_by": actor_user_id,
        },
    )
    await db.execute(stmt)
    return skipped


async def _upsert_signal_defaults(
    db: AsyncSession,
    *,
    company_id: UUID,
    metric_id: UUID,
    actor_user_id: int,
    defaults: Iterable[_SignalDefault],
) -> None:
    # See _upsert_kpi_defaults for the explicit-defaults rationale.
    rows = [
        {
            "id": uuid.uuid4(),
            "company_id": company_id,
            "metric_id": metric_id,
            "signal_code": default.signal_code,
            "weight": default.weight,
            "is_active": True,
            "is_deleted": False,
            "created_at": func.now(),
            "updated_at": func.now(),
            "created_by": actor_user_id,
            "updated_by": actor_user_id,
        }
        for default in defaults
    ]
    stmt = pg_insert(CxoMetricSignalMapping).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_company_metric_signal",
        set_={
            "weight": stmt.excluded.weight,
            "is_active": True,
            "is_deleted": False,
            "updated_at": func.now(),
            "updated_by": actor_user_id,
        },
    )
    await db.execute(stmt)
