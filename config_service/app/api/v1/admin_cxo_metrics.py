"""Admin endpoints for the CXO metric configuration UI.

Route layout matches the established `/api/v1/admin/...` convention (see
admin_kpi_suggestion_mappings.py). Mounted by the gateway at
`/config/api/v1/admin/cxo-metrics/...`.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
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
from config_service.app.models.cxo_metrics import CxoMetricMaster
from config_service.app.repositories.cxo_metrics import (
    CxoMetricKpiMappingRepository,
    CxoMetricMasterRepository,
)
from config_service.app.schemas.cxo_metrics import (
    CxoMetricCreate,
    CxoMetricListResponse,
    CxoMetricRead,
    CxoMetricUpdate,
)


logger = get_file_logger(name="admin_cxo_metrics_api", prefix="admin_cxo_metrics_api")
router = APIRouter(prefix="/admin/cxo-metrics", tags=["admin-cxo-metrics"])


# ---------------------------------------------------------------------------
# GET — list metrics for a company
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=APIResponse[CxoMetricListResponse],
    summary="List CXO metrics for a company",
    description=(
        "Returns the `cxo_metric_master` rows for the given company. "
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
# POST — create a metric
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=APIResponse[CxoMetricRead],
    summary="Create a CXO metric",
    description=(
        "Inserts a row into `cxo_metric_master` for the supplied company. "
        "`metric_code` must be unique within the company (including against "
        "soft-deleted rows, because of the DB-level unique constraint)."
    ),
    responses={
        403: {"description": "Caller is not a platform admin"},
        409: {"description": "metric_code already exists for this company"},
    },
)
async def create_cxo_metric(
    payload: CxoMetricCreate,
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | create_cxo_metric | user_id=%s | company_id=%s | metric_code=%s",
        access.current_user.user_id,
        payload.company_id,
        payload.metric_code,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        repo = CxoMetricMasterRepository(db)
        clash = await repo.get_by_code_any(
            payload.metric_code, company_id=payload.company_id
        )
        if clash is not None:
            raise BusinessException(
                message=(
                    f"metric_code '{payload.metric_code}' already exists for "
                    f"company {payload.company_id}"
                ),
                status_code=409,
            )

        now = datetime.utcnow()
        actor_id = access.current_user.user_id
        row = CxoMetricMaster(
            company_id=payload.company_id,
            metric_code=payload.metric_code,
            display_name=payload.display_name,
            description=payload.description,
            is_active=payload.is_active,
            is_deleted=False,
            created_at=now,
            updated_at=now,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
        await db.commit()
        return success_response(
            data=CxoMetricRead.model_validate(row),
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
            message="Invalid payload", status_code=422, errors=e.errors()
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | create_cxo_metric | user_id=%s", access.current_user.user_id
        )
        return error_response(message="Failed to create CXO metric", status_code=500)


# ---------------------------------------------------------------------------
# PUT — update a metric (display_name / description / is_active)
# ---------------------------------------------------------------------------


@router.put(
    "/{metric_id}",
    response_model=APIResponse[CxoMetricRead],
    summary="Update a CXO metric",
    description=(
        "Partial update — only the supplied fields are applied. `company_id` "
        "and `metric_code` are immutable; delete and re-create to change them."
    ),
    responses={
        400: {"description": "No updatable fields supplied"},
        403: {"description": "Caller is not a platform admin"},
        404: {"description": "Metric not found"},
    },
)
async def update_cxo_metric(
    metric_id: UUID,
    payload: CxoMetricUpdate,
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | update_cxo_metric | user_id=%s | metric_id=%s",
        access.current_user.user_id,
        metric_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        repo = CxoMetricMasterRepository(db)
        metric = await repo.get_by_id(metric_id)
        if metric is None:
            raise BusinessException(
                message=f"CXO metric {metric_id} not found", status_code=404
            )

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise BusinessException(
                message="No updatable fields supplied", status_code=400
            )

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
            message="Invalid payload", status_code=422, errors=e.errors()
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | update_cxo_metric | user_id=%s", access.current_user.user_id
        )
        return error_response(message="Failed to update CXO metric", status_code=500)


# ---------------------------------------------------------------------------
# DELETE — soft-delete a metric (and cascade-soft-delete its KPI mappings)
# ---------------------------------------------------------------------------


@router.delete(
    "/{metric_id}",
    response_model=APIResponse[dict],
    summary="Soft-delete a CXO metric",
    description=(
        "Sets `is_active=false, is_deleted=true` on the metric and cascade-"
        "soft-deletes every active row in `cxo_metric_kpi_mapping` that "
        "references it. Returns the count of mapping rows affected."
    ),
    responses={
        403: {"description": "Caller is not a platform admin"},
        404: {"description": "Metric not found"},
    },
)
async def delete_cxo_metric(
    metric_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_metrics_write),
):
    logger.info(
        "REQUEST | delete_cxo_metric | user_id=%s | metric_id=%s",
        access.current_user.user_id,
        metric_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        repo = CxoMetricMasterRepository(db)
        metric = await repo.get_by_id(metric_id)
        if metric is None:
            raise BusinessException(
                message=f"CXO metric {metric_id} not found", status_code=404
            )

        actor_id = access.current_user.user_id
        mapping_deleted = await CxoMetricKpiMappingRepository(db).soft_delete_for_metric(
            company_id=metric.company_id,
            metric_id=metric.id,
            actor_user_id=actor_id,
        )

        metric.is_active = False
        metric.is_deleted = True
        metric.updated_at = datetime.utcnow()
        metric.updated_by = actor_id
        await db.commit()

        return success_response(
            data={"kpi_mappings_deleted": mapping_deleted},
            message="CXO metric deleted successfully",
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
