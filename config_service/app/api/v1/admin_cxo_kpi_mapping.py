from __future__ import annotations
"""Admin CRUD endpoints for `cxo_metric_kpi_mapping`.

Per-company KPI weights attached to a `cxo_metric_master` row. A mapping is a
set of rows sharing `(company_id, metric_id)`; each row pins one `kpi_key`
with its `weight`.

Routes mounted under `/api/v1/admin/cxo-kpi-mapping`.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.cxo_metrics_dependencies import (
    CxoAccessContext,
    require_cxo_metrics_read,
    require_cxo_metrics_write,
)
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.models.cxo_metrics import (
    CxoMetricKpiMapping,
    CxoMetricMaster,
)
from config_service.app.models.kpi import KPI
from config_service.app.repositories.cxo_metrics import (
    CxoMetricKpiMappingRepository,
    CxoMetricMasterRepository,
)
from config_service.app.schemas.cxo_metrics import (
    CxoKpiMappingCreateRequest,
    CxoKpiMappingListResponse,
    CxoKpiMappingRead,
    CxoKpiMappingStatusUpdate,
    CxoKpiMappingUpdateRequest,
)
from config_service.app.services.cxo_metrics import assert_kpi_keys_belong_to_company


logger = get_file_logger(
    name="admin_cxo_kpi_mapping_api", prefix="admin_cxo_kpi_mapping_api"
)
router = APIRouter(prefix="/admin/cxo-kpi-mapping", tags=["admin-cxo-kpi-mapping"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _mapping_read(
    mapping: CxoMetricKpiMapping, kpi_name: str | None
) -> CxoKpiMappingRead:
    """Build a CxoKpiMappingRead from the ORM row + the joined KPI display name."""
    read = CxoKpiMappingRead.model_validate(mapping)
    read.kpi_name = kpi_name
    return read


async def _get_metric_for_company(
    db: AsyncSession, *, metric_id: UUID, company_id: UUID
) -> CxoMetricMaster:
    """Fetch the metric and assert it belongs to company_id (defends against a
    caller supplying a metric_id from a sibling tenant)."""
    stmt = select(CxoMetricMaster).where(
        CxoMetricMaster.id == metric_id,
        CxoMetricMaster.is_deleted == False,  # noqa: E712
    )
    metric = (await db.execute(stmt)).scalar_one_or_none()
    if metric is None:
        raise BusinessException(
            message=f"CXO metric {metric_id} not found", status_code=404
        )
    if metric.company_id != company_id:
        raise BusinessException(
            message="metric_id does not belong to the supplied company_id",
            status_code=400,
        )
    return metric


# ---------------------------------------------------------------------------
# POST — create one or more KPI mappings
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=APIResponse[CxoKpiMappingListResponse],
    summary="Add one or more KPI mappings to a metric",
    description=(
        "Inserts new active rows into `cxo_metric_kpi_mapping`. Fails with 409 "
        "if any (company_id, metric_id, kpi_key) tuple is already active."
    ),
    responses={
        400: {"description": "Invalid metric_id / kpi_key for this company"},
        403: {"description": "Caller is not a platform admin"},
        409: {"description": "One of the kpi_keys is already mapped"},
    },
)
async def create_kpi_mappings(
    payload: CxoKpiMappingCreateRequest,
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | create_kpi_mappings | user_id=%s | company_id=%s | metric_id=%s | n=%d",
        access.current_user.user_id,
        payload.company_id,
        payload.metric_id,
        len(payload.kpi_mappings),
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        await _get_metric_for_company(
            db, metric_id=payload.metric_id, company_id=payload.company_id
        )
        await assert_kpi_keys_belong_to_company(
            db,
            company_id=payload.company_id,
            kpi_keys=[item.kpi_key for item in payload.kpi_mappings],
        )

        existing = (
            await db.execute(
                select(CxoMetricKpiMapping.kpi_key).where(
                    CxoMetricKpiMapping.company_id == payload.company_id,
                    CxoMetricKpiMapping.metric_id == payload.metric_id,
                    CxoMetricKpiMapping.kpi_key.in_(
                        [item.kpi_key for item in payload.kpi_mappings]
                    ),
                    CxoMetricKpiMapping.is_active == True,  # noqa: E712
                )
            )
        ).all()
        if existing:
            dupes = ", ".join(str(row[0]) for row in existing)
            raise BusinessException(
                message=f"Active mapping already exists for kpi_key(s): {dupes}",
                status_code=409,
            )

        now = datetime.utcnow()
        actor_id = access.current_user.user_id
        rows: list[CxoMetricKpiMapping] = []
        for item in payload.kpi_mappings:
            row = CxoMetricKpiMapping(
                company_id=payload.company_id,
                metric_id=payload.metric_id,
                kpi_key=item.kpi_key,
                weight=item.weight,
                is_active=True,
                is_deleted=False,
                created_at=now,
                updated_at=now,
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(row)
            rows.append(row)
        await db.flush()
        for row in rows:
            await db.refresh(row)
        await db.commit()

        return success_response(
            data=CxoKpiMappingListResponse(
                items=[CxoKpiMappingRead.model_validate(r) for r in rows]
            ),
            message="KPI mapping(s) created successfully",
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | create_kpi_mappings | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        await db.rollback()
        logger.warning("VALIDATION_ERROR | create_kpi_mappings | %s", e.errors())
        return error_response(
            message="Invalid payload", status_code=422, errors=e.errors()
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | create_kpi_mappings | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to create KPI mapping", status_code=500
        )


# ---------------------------------------------------------------------------
# GET — list mappings for (company_id, metric_id)
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=APIResponse[CxoKpiMappingListResponse],
    summary="List KPI mappings for a (company, metric)",
    description=(
        "Returns the active KPI mapping rows for the given company + metric. "
        "Pass `include_inactive=true` to also include rows where `is_active` "
        "is false but `is_deleted` is still false."
    ),
)
async def list_kpi_mappings(
    company_id: UUID = Query(..., description="Target company_id"),
    metric_id: UUID = Query(..., description="Target cxo_metric_master.id"),
    include_inactive: bool = Query(
        False, description="Include rows where is_active=false"
    ),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_read),
):
    logger.info(
        "REQUEST | list_kpi_mappings | user_id=%s | company_id=%s | metric_id=%s | include_inactive=%s",
        access.current_user.user_id,
        company_id,
        metric_id,
        include_inactive,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        stmt = (
            select(CxoMetricKpiMapping, KPI.display_name)
            .outerjoin(KPI, KPI.kpi_key == CxoMetricKpiMapping.kpi_key)
            .where(
                CxoMetricKpiMapping.company_id == company_id,
                CxoMetricKpiMapping.metric_id == metric_id,
                CxoMetricKpiMapping.is_deleted == False,  # noqa: E712
            )
            .order_by(CxoMetricKpiMapping.weight.desc())
        )
        if not include_inactive:
            stmt = stmt.where(CxoMetricKpiMapping.is_active == True)  # noqa: E712
        rows = (await db.execute(stmt)).all()
        return success_response(
            data=CxoKpiMappingListResponse(
                items=[_mapping_read(mapping, kpi_name) for mapping, kpi_name in rows]
            ),
            message="KPI mappings fetched successfully",
        )
    except Exception:
        logger.exception(
            "ERROR | list_kpi_mappings | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to fetch KPI mappings", status_code=500
        )


# ---------------------------------------------------------------------------
# GET single by id
# ---------------------------------------------------------------------------


@router.get(
    "/{mapping_id}",
    response_model=APIResponse[CxoKpiMappingRead],
    summary="Get a single KPI mapping row",
    responses={404: {"description": "Mapping not found"}},
)
async def get_kpi_mapping(
    mapping_id: UUID,
    company_id: UUID = Query(..., description="Target company_id"),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_read),
):
    logger.info(
        "REQUEST | get_kpi_mapping | user_id=%s | mapping_id=%s | company_id=%s",
        access.current_user.user_id,
        mapping_id,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        stmt = (
            select(CxoMetricKpiMapping, KPI.display_name)
            .outerjoin(KPI, KPI.kpi_key == CxoMetricKpiMapping.kpi_key)
            .where(
                CxoMetricKpiMapping.id == mapping_id,
                CxoMetricKpiMapping.is_deleted == False,  # noqa: E712
            )
        )
        result = (await db.execute(stmt)).first()
        if result is None or result[0].company_id != company_id:
            raise BusinessException(
                message=f"KPI mapping {mapping_id} not found", status_code=404
            )
        mapping, kpi_name = result
        return success_response(
            data=_mapping_read(mapping, kpi_name),
            message="KPI mapping fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_kpi_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | get_kpi_mapping | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to fetch KPI mapping", status_code=500
        )


# ---------------------------------------------------------------------------
# PUT — update weight
# ---------------------------------------------------------------------------


@router.put(
    "/{mapping_id}",
    response_model=APIResponse[CxoKpiMappingRead],
    summary="Update a KPI mapping's weight",
    description=(
        "Replaces `weight` on a single mapping row. `company_id`, `metric_id`, "
        "and `kpi_key` are immutable; to change them, delete and re-create the row."
    ),
    responses={
        403: {"description": "Caller is not a platform admin"},
        404: {"description": "Mapping not found"},
    },
)
async def update_kpi_mapping(
    mapping_id: UUID,
    payload: CxoKpiMappingUpdateRequest,
    company_id: UUID = Query(..., description="Target company_id"),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | update_kpi_mapping | user_id=%s | mapping_id=%s | company_id=%s",
        access.current_user.user_id,
        mapping_id,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        repo = CxoMetricKpiMappingRepository(db)
        row = await repo.get_by_id(mapping_id)
        if row is None or row.company_id != company_id:
            raise BusinessException(
                message=f"KPI mapping {mapping_id} not found", status_code=404
            )

        row.weight = payload.weight
        row.updated_at = datetime.utcnow()
        row.updated_by = access.current_user.user_id

        await db.commit()
        await db.refresh(row)
        return success_response(
            data=CxoKpiMappingRead.model_validate(row),
            message="KPI mapping updated successfully",
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | update_kpi_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        await db.rollback()
        logger.warning("VALIDATION_ERROR | update_kpi_mapping | %s", e.errors())
        return error_response(
            message="Invalid payload", status_code=422, errors=e.errors()
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | update_kpi_mapping | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to update KPI mapping", status_code=500
        )


# ---------------------------------------------------------------------------
# PATCH — toggle is_active (without soft-delete)
# ---------------------------------------------------------------------------


@router.patch(
    "/{mapping_id}/status",
    response_model=APIResponse[CxoKpiMappingRead],
    summary="Toggle is_active on a KPI mapping",
    description=(
        "Sets `is_active` to the supplied value without touching `is_deleted`. "
        "Use this when you want to temporarily disable a KPI's contribution "
        "but keep the row recoverable."
    ),
    responses={
        403: {"description": "Caller is not a platform admin"},
        404: {"description": "Mapping not found"},
    },
)
async def set_kpi_mapping_status(
    mapping_id: UUID,
    payload: CxoKpiMappingStatusUpdate,
    company_id: UUID = Query(..., description="Target company_id"),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | set_kpi_mapping_status | user_id=%s | mapping_id=%s | is_active=%s",
        access.current_user.user_id,
        mapping_id,
        payload.is_active,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        repo = CxoMetricKpiMappingRepository(db)
        row = await repo.get_by_id(mapping_id)
        if row is None or row.company_id != company_id:
            raise BusinessException(
                message=f"KPI mapping {mapping_id} not found", status_code=404
            )

        row.is_active = payload.is_active
        row.updated_at = datetime.utcnow()
        row.updated_by = access.current_user.user_id
        await db.commit()
        await db.refresh(row)
        return success_response(
            data=CxoKpiMappingRead.model_validate(row),
            message="KPI mapping status updated",
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | set_kpi_mapping_status | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | set_kpi_mapping_status | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to update KPI mapping status", status_code=500
        )


# ---------------------------------------------------------------------------
# DELETE single KPI from mapping
# ---------------------------------------------------------------------------


@router.delete(
    "/{mapping_id}",
    response_model=APIResponse[None],
    summary="Soft-delete a single KPI mapping row",
    description=(
        "Sets `is_active=false` and `is_deleted=true` on the row identified by "
        "`mapping_id`. Use this to remove one KPI from a metric's mapping."
    ),
    responses={
        403: {"description": "Caller is not a platform admin"},
        404: {"description": "Mapping not found"},
    },
)
async def delete_kpi_mapping(
    mapping_id: UUID,
    company_id: UUID = Query(..., description="Target company_id"),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | delete_kpi_mapping | user_id=%s | mapping_id=%s | company_id=%s",
        access.current_user.user_id,
        mapping_id,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        repo = CxoMetricKpiMappingRepository(db)
        row = await repo.get_by_id(mapping_id)
        if row is None or row.company_id != company_id:
            raise BusinessException(
                message=f"KPI mapping {mapping_id} not found", status_code=404
            )

        row.is_active = False
        row.is_deleted = True
        row.updated_at = datetime.utcnow()
        row.updated_by = access.current_user.user_id
        await db.commit()
        return success_response(
            data=None, message="KPI mapping deleted successfully"
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | delete_kpi_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | delete_kpi_mapping | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to delete KPI mapping", status_code=500
        )


# ---------------------------------------------------------------------------
# DELETE the entire mapping for (company_id, metric_id)
# ---------------------------------------------------------------------------


@router.delete(
    "",
    response_model=APIResponse[dict],
    summary="Soft-delete every KPI mapping for a (company, metric)",
    description=(
        "Bulk soft-delete: every active row matching `(company_id, metric_id)` "
        "is set to `is_active=false, is_deleted=true`. Returns the count of "
        "rows affected."
    ),
    responses={403: {"description": "Caller is not a platform admin"}},
)
async def delete_all_kpi_mappings(
    company_id: UUID = Query(..., description="Target company_id"),
    metric_id: UUID = Query(..., description="Target cxo_metric_master.id"),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | delete_all_kpi_mappings | user_id=%s | company_id=%s | metric_id=%s",
        access.current_user.user_id,
        company_id,
        metric_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        deleted = await CxoMetricKpiMappingRepository(db).soft_delete_for_metric(
            company_id=company_id,
            metric_id=metric_id,
            actor_user_id=access.current_user.user_id,
        )
        await db.commit()
        return success_response(
            data={"deleted_count": deleted},
            message="KPI mapping cleared successfully",
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | delete_all_kpi_mappings | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to clear KPI mapping", status_code=500
        )
