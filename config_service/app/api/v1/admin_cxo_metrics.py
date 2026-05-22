"""Admin endpoints for the CXO metric configuration UI.

Route layout matches the established `/api/v1/admin/...` convention (see
admin_kpi_suggestion_mappings.py). The spec's `/api/admin/cxo-metrics/...`
prefix is therefore implemented here as `/api/v1/admin/cxo-metrics/...`,
mounted by the gateway at `/config/api/v1/admin/cxo-metrics/...`.
"""

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.services.audit_log_service import AuditLogService
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.cxo_metrics_dependencies import (
    CxoAccessContext,
    require_cxo_metrics_read,
    require_cxo_metrics_write,
)
from config_service.app.models.cxo_metrics import CxoMetricMaster
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.models.cxo_metrics import (
    CxoMetricKpiMapping,
    CxoMetricSignalMapping,
)
from config_service.app.models.kpi import KPI
from config_service.app.repositories.cxo_metrics import (
    CxoMetricKpiMappingRepository,
    CxoMetricMasterRepository,
    CxoMetricSignalMappingRepository,
)
from config_service.app.schemas.cxo_metrics import (
    CxoMappingResponse,
    CxoMappingUpdateRequest,
    CxoMetricListResponse,
    CxoMetricMasterCreate,
    CxoMetricMasterUpdate,
    CxoMetricRead,
    CxoMetricResetRequest,
    CxoOptionsResponse,
    KpiMappingResponse,
    KpiOption,
    MappingValidationInfo,
    MetricSummary,
    SIGNAL_CODES,
    SIGNAL_DISPLAY_NAMES,
    SignalMappingResponse,
    SignalOption,
)
from config_service.app.services.cxo_metrics import (
    assert_kpi_keys_belong_to_company,
    load_metric_and_mapping,
    mapping_snapshot,
    request_snapshot,
    validate_mapping_payload,
    validation_rule_text,
)
from config_service.app.services.cxo_seeder import seed_default_cxo_mappings
from sqlalchemy import select


logger = get_file_logger(name="admin_cxo_metrics_api", prefix="admin_cxo_metrics_api")
router = APIRouter(prefix="/admin/cxo-metrics", tags=["admin-cxo-metrics"])


# ---------------------------------------------------------------------------
# GET /cxo-metrics — list the metric master rows
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=APIResponse[CxoMetricListResponse],
    summary="List CXO metrics for a company",
    description=(
        "Returns the metric catalog (PRODUCTIVITY, ENGAGEMENT, ABSENTEEISM, "
        "plus any company-specific additions) scoped to the given company. "
        "Open to platform admins and company admins."
    ),
    responses={403: {"description": "Caller's role cannot read CXO metrics"}},
)
async def list_cxo_metrics(
    company_id: UUID = Query(..., description="Target company_id"),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_read),
):
    logger.info(
        "REQUEST | list_cxo_metrics | user_id=%s | role=%s | company_id=%s",
        access.current_user.user_id,
        access.resolved_role,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        metrics = await CxoMetricMasterRepository(db).list_active(
            company_id=company_id
        )
        return success_response(
            data=CxoMetricListResponse(
                items=[CxoMetricRead.model_validate(m) for m in metrics]
            ),
            message="CXO metrics fetched successfully",
        )
    except Exception:
        logger.exception(
            "ERROR | list_cxo_metrics | user_id=%s", access.current_user.user_id
        )
        return error_response(message="Failed to fetch CXO metrics", status_code=500)


# ---------------------------------------------------------------------------
# POST /cxo-metrics — create a new metric definition (cxo_metric_master row)
# UI-driven equivalent of the SQL seed in seed_cxo_metric_master.sql, so an
# operator can add PRODUCTIVITY / ENGAGEMENT / ABSENTEEISM (or a new metric)
# through the form instead of running psql.
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=APIResponse[CxoMetricRead],
    summary="Create a CXO metric definition",
    description=(
        "Inserts a new metric row into `cxo_metric_master` scoped to "
        "`company_id`. `metric_code` must be unique within the company. "
        "`formula_type` is one of `WEIGHTED_AVG` / `DEFICIT_SUM` / `COMPOSITE`."
    ),
    responses={
        400: {"description": "metric_code already exists or validation failed"},
        403: {"description": "Caller is not a platform admin"},
    },
)
async def create_cxo_metric(
    payload: CxoMetricMasterCreate,
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | create_cxo_metric | user_id=%s | company_id=%s | metric_code=%s | formula_type=%s",
        access.current_user.user_id,
        payload.company_id,
        payload.metric_code,
        payload.formula_type,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        repo = CxoMetricMasterRepository(db)
        existing = await repo.get_by_code(
            payload.metric_code, company_id=payload.company_id
        )
        if existing is not None:
            raise BusinessException(
                message=(
                    f"metric_code '{payload.metric_code}' already exists "
                    f"for company {payload.company_id}"
                ),
                status_code=400,
            )

        # Explicit timestamps because cxo_metric_master uses AuditMixin which
        # declares its created_at/updated_at defaults Python-side only. When
        # the table was built by Base.metadata.create_all (rather than the
        # SQL migration) there are no server defaults to fall back on, so
        # ORM .add() would otherwise leave them NULL and the NOT NULL
        # constraint would fire.
        from datetime import datetime
        now = datetime.utcnow()
        row = CxoMetricMaster(
            company_id=payload.company_id,
            metric_code=payload.metric_code,
            display_name=payload.display_name,
            unit=payload.unit,
            scale_min=payload.scale_min,
            scale_max=payload.scale_max,
            baseline=payload.baseline,
            formula_type=payload.formula_type,
            description=payload.description,
            methodology_ref=payload.methodology_ref,
            is_active=True,
            is_deleted=False,
            created_at=now,
            updated_at=now,
            created_by=access.current_user.user_id,
            updated_by=access.current_user.user_id,
        )
        created = await repo.create(row)
        await db.commit()
        await db.refresh(created)
        return success_response(
            data=CxoMetricRead.model_validate(created),
            message="CXO metric created successfully",
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | create_cxo_metric | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        await db.rollback()
        logger.warning("VALIDATION_ERROR | create_cxo_metric | %s", e.errors())
        return error_response(
            message="Invalid CXO metric payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | create_cxo_metric | user_id=%s", access.current_user.user_id
        )
        return error_response(message="Failed to create CXO metric", status_code=500)


# ---------------------------------------------------------------------------
# GET /cxo-metrics/options — KPI + signal options for the UI
# ---------------------------------------------------------------------------


@router.get(
    "/options",
    response_model=APIResponse[CxoOptionsResponse],
    summary="List configurable options",
    description=(
        "Returns the KPI list for the given company (suitable for dropdowns) "
        "plus the static signal vocabulary used by COMPOSITE metrics."
    ),
    responses={403: {"description": "Caller cannot access this company"}},
)
async def list_cxo_options(
    company_id: UUID = Query(..., description="Target company_id"),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_read),
):
    logger.info(
        "REQUEST | list_cxo_options | user_id=%s | company_id=%s",
        access.current_user.user_id,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        stmt = (
            select(KPI.kpi_key, KPI.display_name)
            .where(
                KPI.company_id == company_id,
                KPI.is_active == True,  # noqa: E712
                KPI.is_deleted == False,  # noqa: E712
            )
            .order_by(KPI.display_name.asc())
        )
        rows = (await db.execute(stmt)).all()
        return success_response(
            data=CxoOptionsResponse(
                kpis=[KpiOption(kpi_key=row[0], display_name=row[1]) for row in rows],
                signals=[
                    SignalOption(
                        signal_code=code, display_name=SIGNAL_DISPLAY_NAMES[code]
                    )
                    for code in SIGNAL_CODES
                ],
            ),
            message="CXO options fetched successfully",
        )
    except Exception:
        logger.exception(
            "ERROR | list_cxo_options | user_id=%s", access.current_user.user_id
        )
        return error_response(message="Failed to fetch CXO options", status_code=500)


# ---------------------------------------------------------------------------
# GET /cxo-metrics/{metric_code} — fetch a single metric definition
# ---------------------------------------------------------------------------


@router.get(
    "/{metric_code}",
    response_model=APIResponse[CxoMetricRead],
    summary="Get a CXO metric definition",
    description=(
        "Returns the `cxo_metric_master` row identified by "
        "`(company_id, metric_code)`."
    ),
    responses={
        403: {"description": "Caller cannot access this company"},
        404: {"description": "Metric not found"},
    },
)
async def get_cxo_metric(
    metric_code: str,
    company_id: UUID = Query(..., description="Target company_id"),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_read),
):
    logger.info(
        "REQUEST | get_cxo_metric | user_id=%s | metric=%s | company_id=%s",
        access.current_user.user_id,
        metric_code,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        metric = await CxoMetricMasterRepository(db).get_by_code(
            metric_code, company_id=company_id
        )
        if metric is None:
            raise BusinessException(
                message=f"Metric '{metric_code}' not found", status_code=404
            )
        return success_response(
            data=CxoMetricRead.model_validate(metric),
            message="CXO metric fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_cxo_metric | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | get_cxo_metric | user_id=%s", access.current_user.user_id
        )
        return error_response(message="Failed to fetch CXO metric", status_code=500)


# ---------------------------------------------------------------------------
# PUT /cxo-metrics/{metric_code} — patch fields on a metric definition.
# `metric_code` / `company_id` / `formula_type` are not editable: those
# affect mapping integrity, so the supported flow is delete + recreate.
# ---------------------------------------------------------------------------


@router.put(
    "/{metric_code}",
    response_model=APIResponse[CxoMetricRead],
    summary="Update a CXO metric definition",
    description=(
        "Updates the editable fields on a `cxo_metric_master` row. Only the "
        "keys present in the request body are applied; `metric_code`, "
        "`company_id`, and `formula_type` are immutable."
    ),
    responses={
        400: {"description": "Validation failed"},
        403: {"description": "Caller is not a platform admin"},
        404: {"description": "Metric not found"},
    },
)
async def update_cxo_metric(
    metric_code: str,
    payload: CxoMetricMasterUpdate,
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | update_cxo_metric | user_id=%s | company_id=%s | metric=%s",
        access.current_user.user_id,
        payload.company_id,
        metric_code,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        repo = CxoMetricMasterRepository(db)
        metric = await repo.get_by_code(metric_code, company_id=payload.company_id)
        if metric is None:
            raise BusinessException(
                message=f"Metric '{metric_code}' not found", status_code=404
            )

        updates = payload.model_dump(exclude_unset=True, exclude={"company_id"})
        if not updates:
            raise BusinessException(
                message="No updatable fields supplied", status_code=400
            )

        from datetime import datetime
        for field, value in updates.items():
            setattr(metric, field, value)
        metric.updated_at = datetime.utcnow()
        metric.updated_by = access.current_user.user_id

        await db.commit()
        await db.refresh(metric)
        return success_response(
            data=CxoMetricRead.model_validate(metric),
            message="CXO metric updated successfully",
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | update_cxo_metric | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        await db.rollback()
        logger.warning("VALIDATION_ERROR | update_cxo_metric | %s", e.errors())
        return error_response(
            message="Invalid CXO metric payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | update_cxo_metric | user_id=%s", access.current_user.user_id
        )
        return error_response(message="Failed to update CXO metric", status_code=500)


# ---------------------------------------------------------------------------
# DELETE /cxo-metrics/{metric_code} — soft-delete a metric and cascade-
# soft-delete its mappings (so stale rows don't reference a hidden master).
# ---------------------------------------------------------------------------


@router.delete(
    "/{metric_code}",
    response_model=APIResponse[None],
    summary="Soft-delete a CXO metric definition",
    description=(
        "Marks the `cxo_metric_master` row inactive and soft-deletes every "
        "associated KPI / signal mapping for the same company in one "
        "transaction."
    ),
    responses={
        403: {"description": "Caller is not a platform admin"},
        404: {"description": "Metric not found"},
    },
)
async def delete_cxo_metric(
    metric_code: str,
    company_id: UUID = Query(..., description="Target company_id"),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | delete_cxo_metric | user_id=%s | company_id=%s | metric=%s",
        access.current_user.user_id,
        company_id,
        metric_code,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        repo = CxoMetricMasterRepository(db)
        metric = await repo.get_by_code(metric_code, company_id=company_id)
        if metric is None:
            raise BusinessException(
                message=f"Metric '{metric_code}' not found", status_code=404
            )

        actor_id = access.current_user.user_id

        # Snapshot the mapping state before we delete it, for audit.
        _, old_kpi_rows_with_name, old_signal_rows = await load_metric_and_mapping(
            db, metric_code=metric_code, company_id=company_id
        )
        old_snapshot = mapping_snapshot(
            kpi_rows=[row[0] for row in old_kpi_rows_with_name],
            signal_rows=old_signal_rows,
        )

        async with db.begin_nested():
            await CxoMetricKpiMappingRepository(db).soft_delete_for_metric(
                company_id=company_id,
                metric_id=metric.id,
                actor_user_id=actor_id,
            )
            await CxoMetricSignalMappingRepository(db).soft_delete_for_metric(
                company_id=company_id,
                metric_id=metric.id,
                actor_user_id=actor_id,
            )

            from datetime import datetime
            metric.is_active = False
            metric.is_deleted = True
            metric.updated_at = datetime.utcnow()
            metric.updated_by = actor_id
            await db.flush()

            AuditLogService(db).queue(
                user_id=actor_id,
                tenant_id=company_id,
                action="DELETE_CXO_METRIC",
                entity="cxo_metric_master",
                old_value={
                    "metric_code": metric.metric_code,
                    "display_name": metric.display_name,
                    "formula_type": metric.formula_type,
                    **old_snapshot,
                },
                new_value=None,
            )

        await db.commit()
        return success_response(
            data=None, message="CXO metric deleted successfully"
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | delete_cxo_metric | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | delete_cxo_metric | user_id=%s", access.current_user.user_id
        )
        return error_response(message="Failed to delete CXO metric", status_code=500)


# ---------------------------------------------------------------------------
# GET /cxo-metrics/{metric_code}/mapping
# ---------------------------------------------------------------------------


@router.get(
    "/{metric_code}/mapping",
    response_model=APIResponse[CxoMappingResponse],
    summary="Get a metric's mapping for a company",
    description=(
        "Returns the active KPI weights (or signal weights, for COMPOSITE "
        "metrics) configured for the given company, plus a validation summary."
    ),
    responses={
        403: {"description": "Caller cannot access this company"},
        404: {"description": "Metric not found"},
    },
)
async def get_cxo_metric_mapping(
    metric_code: str,
    company_id: UUID = Query(..., description="Target company_id"),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_read),
):
    logger.info(
        "REQUEST | get_cxo_metric_mapping | user_id=%s | metric=%s | company_id=%s",
        access.current_user.user_id,
        metric_code,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        metric, kpi_rows, signal_rows = await load_metric_and_mapping(
            db, metric_code=metric_code, company_id=company_id
        )
        weight_sum = _sum_for_summary(metric.formula_type, kpi_rows, signal_rows)
        is_valid = _is_weight_sum_valid(metric.formula_type, weight_sum, kpi_rows)
        return success_response(
            data=CxoMappingResponse(
                metric=MetricSummary(
                    metric_code=metric.metric_code,
                    display_name=metric.display_name,
                    formula_type=metric.formula_type,
                    baseline=metric.baseline,
                ),
                kpi_mappings=[
                    KpiMappingResponse(
                        kpi_key=row[0].kpi_key,
                        kpi_name=row[1],
                        weight=row[0].weight,
                        threshold=row[0].threshold,
                    )
                    for row in kpi_rows
                ],
                signal_mappings=[
                    SignalMappingResponse(
                        signal_code=row.signal_code,
                        weight=row.weight,
                    )
                    for row in signal_rows
                ],
                validation=MappingValidationInfo(
                    weight_sum=weight_sum,
                    is_valid=is_valid,
                    rule=validation_rule_text(metric.formula_type),
                ),
            ),
            message="CXO mapping fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_cxo_metric_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | get_cxo_metric_mapping | user_id=%s", access.current_user.user_id
        )
        return error_response(message="Failed to fetch CXO mapping", status_code=500)


def _sum_for_summary(
    formula_type: str,
    kpi_rows: list[tuple[CxoMetricKpiMapping, str]],
    signal_rows: list[CxoMetricSignalMapping],
) -> Decimal:
    if formula_type == "COMPOSITE":
        return sum((row.weight for row in signal_rows), Decimal("0"))
    return sum((row[0].weight for row in kpi_rows), Decimal("0"))


def _is_weight_sum_valid(
    formula_type: str,
    weight_sum: Decimal,
    kpi_rows: list[tuple[CxoMetricKpiMapping, str]],
) -> bool:
    if formula_type in ("WEIGHTED_AVG", "COMPOSITE"):
        return abs(weight_sum - Decimal("1.000")) <= Decimal("0.001")
    if formula_type == "DEFICIT_SUM":
        return all(row[0].threshold is not None for row in kpi_rows) and len(kpi_rows) > 0
    return False


# ---------------------------------------------------------------------------
# PUT /cxo-metrics/{metric_code}/mapping
# ---------------------------------------------------------------------------


@router.put(
    "/{metric_code}/mapping",
    response_model=APIResponse[CxoMappingResponse],
    summary="Replace a metric's mapping for a company",
    description=(
        "Validates the payload against the metric's formula_type, soft-deletes "
        "the previous mapping rows, inserts the new ones, and writes one audit "
        "log entry. All steps run in a single transaction; any failure rolls "
        "the whole thing back."
    ),
    responses={
        400: {"description": "Validation failed"},
        403: {"description": "Caller is not a platform admin"},
        404: {"description": "Metric not found"},
    },
)
async def put_cxo_metric_mapping(
    metric_code: str,
    payload: CxoMappingUpdateRequest,
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | put_cxo_metric_mapping | user_id=%s | metric=%s | company_id=%s",
        access.current_user.user_id,
        metric_code,
        payload.company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        metric = await CxoMetricMasterRepository(db).get_by_code(
            metric_code, company_id=payload.company_id
        )
        if metric is None:
            raise BusinessException(
                message=f"Metric '{metric_code}' not found", status_code=404
            )

        # 1. Validate the payload BEFORE touching the DB.
        weight_sum = validate_mapping_payload(
            formula_type=metric.formula_type, payload=payload
        )
        await assert_kpi_keys_belong_to_company(
            db,
            company_id=payload.company_id,
            kpi_keys=[item.kpi_key for item in payload.kpi_mappings],
        )

        # 2. Capture the old snapshot for the audit log.
        _, old_kpi_rows_with_name, old_signal_rows = await load_metric_and_mapping(
            db, metric_code=metric_code, company_id=payload.company_id
        )
        old_kpi_rows = [row[0] for row in old_kpi_rows_with_name]
        old_snapshot = mapping_snapshot(
            kpi_rows=old_kpi_rows, signal_rows=old_signal_rows
        )
        new_snapshot = request_snapshot(payload)

        # 3. Transactional soft-delete + insert.
        actor_id = access.current_user.user_id
        kpi_repo = CxoMetricKpiMappingRepository(db)
        signal_repo = CxoMetricSignalMappingRepository(db)

        async with db.begin_nested():
            await kpi_repo.soft_delete_for_metric(
                company_id=payload.company_id,
                metric_id=metric.id,
                actor_user_id=actor_id,
            )
            await signal_repo.soft_delete_for_metric(
                company_id=payload.company_id,
                metric_id=metric.id,
                actor_user_id=actor_id,
            )
            for item in payload.kpi_mappings:
                db.add(
                    CxoMetricKpiMapping(
                        company_id=payload.company_id,
                        metric_id=metric.id,
                        kpi_key=item.kpi_key,
                        weight=item.weight,
                        threshold=item.threshold,
                        is_active=True,
                        is_deleted=False,
                        created_by=actor_id,
                        updated_by=actor_id,
                    )
                )
            for item in payload.signal_mappings:
                db.add(
                    CxoMetricSignalMapping(
                        company_id=payload.company_id,
                        metric_id=metric.id,
                        signal_code=item.signal_code,
                        weight=item.weight,
                        is_active=True,
                        is_deleted=False,
                        created_by=actor_id,
                        updated_by=actor_id,
                    )
                )
            await db.flush()
            # queue() — log() commits internally and would close the
            # surrounding begin_nested() savepoint.
            AuditLogService(db).queue(
                user_id=actor_id,
                tenant_id=payload.company_id,
                action="UPDATE_CXO_MAPPING",
                entity="cxo_metric_kpi_mapping",
                old_value=old_snapshot,
                new_value=new_snapshot,
            )

        # 4. Reload the saved state so we return the canonical response.
        metric, kpi_rows, signal_rows = await load_metric_and_mapping(
            db, metric_code=metric_code, company_id=payload.company_id
        )
        return success_response(
            data=CxoMappingResponse(
                metric=MetricSummary(
                    metric_code=metric.metric_code,
                    display_name=metric.display_name,
                    formula_type=metric.formula_type,
                    baseline=metric.baseline,
                ),
                kpi_mappings=[
                    KpiMappingResponse(
                        kpi_key=row[0].kpi_key,
                        kpi_name=row[1],
                        weight=row[0].weight,
                        threshold=row[0].threshold,
                    )
                    for row in kpi_rows
                ],
                signal_mappings=[
                    SignalMappingResponse(
                        signal_code=row.signal_code, weight=row.weight
                    )
                    for row in signal_rows
                ],
                validation=MappingValidationInfo(
                    weight_sum=weight_sum,
                    is_valid=True,
                    rule=validation_rule_text(metric.formula_type),
                ),
            ),
            message="CXO mapping updated successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | put_cxo_metric_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | put_cxo_metric_mapping | %s", e.errors())
        return error_response(
            message="Invalid CXO mapping payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        logger.exception(
            "ERROR | put_cxo_metric_mapping | user_id=%s", access.current_user.user_id
        )
        return error_response(message="Failed to update CXO mapping", status_code=500)


# ---------------------------------------------------------------------------
# POST /cxo-metrics/{metric_code}/reset
# ---------------------------------------------------------------------------


@router.post(
    "/{metric_code}/reset",
    response_model=APIResponse[CxoMappingResponse],
    summary="Reset a metric's mapping to defaults",
    description=(
        "Soft-deletes the company's current mapping for this metric and "
        "re-seeds it with the platform defaults from the methodology document."
    ),
    responses={
        403: {"description": "Caller is not a platform admin"},
        404: {"description": "Metric not found"},
    },
)
async def reset_cxo_metric_mapping(
    metric_code: str,
    payload: CxoMetricResetRequest,
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | reset_cxo_metric_mapping | user_id=%s | metric=%s | company_id=%s",
        access.current_user.user_id,
        metric_code,
        payload.company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        metric = await CxoMetricMasterRepository(db).get_by_code(
            metric_code, company_id=payload.company_id
        )
        if metric is None:
            raise BusinessException(
                message=f"Metric '{metric_code}' not found", status_code=404
            )

        actor_id = access.current_user.user_id

        # Snapshot the old state for the audit log.
        _, old_kpi_rows_with_name, old_signal_rows = await load_metric_and_mapping(
            db, metric_code=metric_code, company_id=payload.company_id
        )
        old_snapshot = mapping_snapshot(
            kpi_rows=[row[0] for row in old_kpi_rows_with_name],
            signal_rows=old_signal_rows,
        )

        async with db.begin_nested():
            await CxoMetricKpiMappingRepository(db).soft_delete_for_metric(
                company_id=payload.company_id,
                metric_id=metric.id,
                actor_user_id=actor_id,
            )
            await CxoMetricSignalMappingRepository(db).soft_delete_for_metric(
                company_id=payload.company_id,
                metric_id=metric.id,
                actor_user_id=actor_id,
            )
            await db.flush()
            seed_result = await seed_default_cxo_mappings(
                db,
                company_id=payload.company_id,
                actor_user_id=actor_id,
                metric_codes=[metric_code],
            )
            # Snapshot the new state and write a single RESET_CXO_MAPPING entry.
            _, new_kpi_rows_with_name, new_signal_rows = await load_metric_and_mapping(
                db, metric_code=metric_code, company_id=payload.company_id
            )
            new_snapshot = mapping_snapshot(
                kpi_rows=[row[0] for row in new_kpi_rows_with_name],
                signal_rows=new_signal_rows,
            )
            # queue() — log() commits internally and would close the
            # surrounding begin_nested() savepoint.
            AuditLogService(db).queue(
                user_id=actor_id,
                tenant_id=payload.company_id,
                action="RESET_CXO_MAPPING",
                entity="cxo_metric_kpi_mapping",
                old_value=old_snapshot,
                new_value={
                    **new_snapshot,
                    "skipped_kpis": seed_result.skipped_kpis,
                },
            )

        metric, kpi_rows, signal_rows = await load_metric_and_mapping(
            db, metric_code=metric_code, company_id=payload.company_id
        )
        weight_sum = _sum_for_summary(metric.formula_type, kpi_rows, signal_rows)
        is_valid = _is_weight_sum_valid(metric.formula_type, weight_sum, kpi_rows)
        return success_response(
            data=CxoMappingResponse(
                metric=MetricSummary(
                    metric_code=metric.metric_code,
                    display_name=metric.display_name,
                    formula_type=metric.formula_type,
                    baseline=metric.baseline,
                ),
                kpi_mappings=[
                    KpiMappingResponse(
                        kpi_key=row[0].kpi_key,
                        kpi_name=row[1],
                        weight=row[0].weight,
                        threshold=row[0].threshold,
                    )
                    for row in kpi_rows
                ],
                signal_mappings=[
                    SignalMappingResponse(
                        signal_code=row.signal_code, weight=row.weight
                    )
                    for row in signal_rows
                ],
                validation=MappingValidationInfo(
                    weight_sum=weight_sum,
                    is_valid=is_valid,
                    rule=validation_rule_text(metric.formula_type),
                ),
            ),
            message="CXO mapping reset to defaults",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | reset_cxo_metric_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | reset_cxo_metric_mapping | user_id=%s", access.current_user.user_id
        )
        return error_response(message="Failed to reset CXO mapping", status_code=500)
