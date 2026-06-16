from __future__ import annotations
"""CRUD endpoints for `wellness_dimension` — per-company catalog of wellness
dimensions that group KPIs (sleep, stress, etc.).

Mounted by the gateway at `/config/api/v1/dimensions/...`.

Tenant scoping:
  * Platform admin (Super Admin / Ayumonk Admin) — passes the target
    `company_id` via query param.
  * Company admin / HR — forced onto their own tenant; the query param is
    ignored if supplied.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.core.wellness_dimensions_dependencies import (
    DimensionAccessContext,
    require_dimensions_access,
)
from config_service.app.models.wellness_dimensions import WellnessDimension
from config_service.app.repositories.wellness_dimensions import (
    WellnessDimensionRepository,
)
from config_service.app.schemas.wellness_dimensions import (
    WellnessDimensionCreateRequest,
    WellnessDimensionListResponse,
    WellnessDimensionResponse,
    WellnessDimensionUpdateRequest,
)


logger = get_file_logger(name="wellness_dimensions_api", prefix="wellness_dimensions_api")
router = APIRouter(prefix="/dimensions", tags=["wellness-dimensions"])


RESERVED_DIMENSION_KEYS = {"wellnessindex"}


def _resolve_company_id(
    *, access: DimensionAccessContext, company_id_param: UUID | None
) -> UUID:
    """Platform admins must pass `company_id`; company-tier callers are
    forced onto their own tenant — the query param is ignored. company_id is
    NEVER trusted from the request for non-platform callers."""
    if access.is_platform_admin:
        if company_id_param is None:
            raise BusinessException(
                message="company_id is required for platform admins",
                status_code=400,
            )
        return company_id_param
    if access.tenant_id is None:
        raise BusinessException(
            message="No tenant assignment on current user", status_code=403
        )
    return access.tenant_id


def _to_response(
    dimension: WellnessDimension, kpi_count: int = 0
) -> WellnessDimensionResponse:
    return WellnessDimensionResponse(
        id=dimension.id,
        company_id=dimension.company_id,
        dimension_key=dimension.dimension_key,
        dimension_label=dimension.dimension_label,
        display_order=int(dimension.display_order),
        is_active=bool(dimension.is_active),
        kpi_count=kpi_count,
        created_at=dimension.created_at,
        updated_at=dimension.updated_at,
        created_by=dimension.created_by,
        updated_by=dimension.updated_by,
    )


# ---------------------------------------------------------------------------
# GET — list dimensions with their active KPI counts
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=APIResponse[WellnessDimensionListResponse],
    summary="List wellness dimensions for the caller's company",
    description=(
        "Returns every wellness dimension scoped to the resolved company, "
        "ordered by `display_order`, with a `kpi_count` of active KPI mappings."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller's role cannot access this endpoint"},
    },
)
async def list_dimensions(
    company_id: UUID | None = Query(
        default=None,
        description=(
            "Required for platform admins; ignored for company-tier callers."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    access: DimensionAccessContext = Depends(require_dimensions_access),
):
    logger.info(
        "REQUEST | list_dimensions | user_id=%s | role=%s | company_id=%s",
        access.current_user.user_id,
        access.resolved_role,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        repo = WellnessDimensionRepository(db)
        rows = await repo.list_with_kpi_counts(company_id=resolved_company_id)
        return success_response(
            data=WellnessDimensionListResponse(
                items=[_to_response(dim, kpi_count) for dim, kpi_count in rows]
            ),
            message="Wellness dimensions fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | list_dimensions | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | list_dimensions | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to fetch wellness dimensions", status_code=500
        )


# ---------------------------------------------------------------------------
# POST — create a dimension
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=APIResponse[WellnessDimensionResponse],
    summary="Create a wellness dimension",
    description=(
        "Inserts a new row into `wellness_dimension` for the resolved company. "
        "`dimension_key` is auto-lowercased, has whitespace runs replaced "
        "with underscores, and must be unique within the company. The "
        "reserved key 'wellnessindex' is rejected."
    ),
    responses={
        400: {
            "description": (
                "Reserved or duplicate dimension_key, or company_id missing "
                "for a platform admin"
            )
        },
        403: {"description": "Caller's role cannot access this endpoint"},
    },
)
async def create_dimension(
    payload: WellnessDimensionCreateRequest,
    company_id: UUID | None = Query(
        default=None,
        description=(
            "Required for platform admins; ignored for company-tier callers."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    access: DimensionAccessContext = Depends(require_dimensions_access),
):
    logger.info(
        "REQUEST | create_dimension | user_id=%s | dimension_key=%s | company_id=%s",
        access.current_user.user_id,
        payload.dimension_key,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )

        if payload.dimension_key in RESERVED_DIMENSION_KEYS:
            raise BusinessException(
                message=(
                    f"dimension_key '{payload.dimension_key}' is reserved and "
                    "cannot be used"
                ),
                status_code=400,
            )

        repo = WellnessDimensionRepository(db)
        clash = await repo.get_by_key(
            payload.dimension_key, company_id=resolved_company_id
        )
        if clash is not None:
            raise BusinessException(
                message=(
                    f"dimension_key '{payload.dimension_key}' already exists "
                    "for this company"
                ),
                status_code=400,
            )

        dimension = WellnessDimension(
            company_id=resolved_company_id,
            dimension_key=payload.dimension_key,
            dimension_label=payload.dimension_label,
            display_order=payload.display_order,
            is_active=payload.is_active,
            is_deleted=False,
        )
        db.add(dimension)
        await db.flush()
        await db.refresh(dimension)
        await db.commit()
        return success_response(
            data=_to_response(dimension, kpi_count=0),
            message="Wellness dimension created successfully",
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | create_dimension | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        await db.rollback()
        logger.warning("VALIDATION_ERROR | create_dimension | %s", e.errors())
        return error_response(
            message="Invalid wellness dimension payload",
            status_code=422,
            errors=e.errors(),
        )
    except IntegrityError:
        await db.rollback()
        logger.warning(
            "INTEGRITY_ERROR | create_dimension | dimension_key=%s",
            payload.dimension_key,
        )
        return error_response(
            message=(
                f"dimension_key '{payload.dimension_key}' already exists for "
                "this company"
            ),
            status_code=400,
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | create_dimension | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to create wellness dimension", status_code=500
        )


# ---------------------------------------------------------------------------
# PATCH — update a dimension (label / display_order / is_active)
# ---------------------------------------------------------------------------


@router.patch(
    "/{dimension_id}",
    response_model=APIResponse[WellnessDimensionResponse],
    summary="Update a wellness dimension",
    description=(
        "Partial update — only the supplied fields are applied. `dimension_key`"
        " is immutable after creation."
    ),
    responses={
        400: {
            "description": (
                "No updatable fields supplied, or company_id missing for a "
                "platform admin"
            )
        },
        403: {"description": "Caller's role cannot access this endpoint"},
        404: {"description": "Dimension not found for this tenant"},
    },
)
async def update_dimension(
    dimension_id: int,
    payload: WellnessDimensionUpdateRequest,
    company_id: UUID | None = Query(
        default=None,
        description=(
            "Required for platform admins; ignored for company-tier callers."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    access: DimensionAccessContext = Depends(require_dimensions_access),
):
    logger.info(
        "REQUEST | update_dimension | user_id=%s | dimension_id=%s | company_id=%s",
        access.current_user.user_id,
        dimension_id,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        repo = WellnessDimensionRepository(db)
        dimension = await repo.get_by_id(
            dimension_id, company_id=resolved_company_id
        )
        if dimension is None:
            raise BusinessException(
                message=f"Wellness dimension {dimension_id} not found",
                status_code=404,
            )

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise BusinessException(
                message="No updatable fields supplied", status_code=400
            )

        for field, value in updates.items():
            setattr(dimension, field, value)
        dimension.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(dimension)
        kpi_count = await repo.active_mapping_count(
            dimension.id, company_id=resolved_company_id
        )
        return success_response(
            data=_to_response(dimension, kpi_count=kpi_count),
            message="Wellness dimension updated successfully",
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | update_dimension | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        await db.rollback()
        logger.warning("VALIDATION_ERROR | update_dimension | %s", e.errors())
        return error_response(
            message="Invalid wellness dimension payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | update_dimension | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to update wellness dimension", status_code=500
        )


# ---------------------------------------------------------------------------
# DELETE — hard-delete a dimension (blocked if any active mappings remain)
# ---------------------------------------------------------------------------


@router.delete(
    "/{dimension_id}",
    response_model=APIResponse[dict],
    summary="Delete a wellness dimension",
    description=(
        "Hard-deletes the row. Refuses (400) if any active rows exist in "
        "`wellness_dimension_kpi_mapping` for this dimension."
    ),
    responses={
        400: {
            "description": (
                "Active KPI mappings still attached, or company_id missing "
                "for a platform admin"
            )
        },
        403: {"description": "Caller's role cannot access this endpoint"},
        404: {"description": "Dimension not found for this tenant"},
    },
)
async def delete_dimension(
    dimension_id: int,
    company_id: UUID | None = Query(
        default=None,
        description=(
            "Required for platform admins; ignored for company-tier callers."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    access: DimensionAccessContext = Depends(require_dimensions_access),
):
    logger.info(
        "REQUEST | delete_dimension | user_id=%s | dimension_id=%s | company_id=%s",
        access.current_user.user_id,
        dimension_id,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        repo = WellnessDimensionRepository(db)
        dimension = await repo.get_by_id(
            dimension_id, company_id=resolved_company_id
        )
        if dimension is None:
            raise BusinessException(
                message=f"Wellness dimension {dimension_id} not found",
                status_code=404,
            )

        active_count = await repo.active_mapping_count(
            dimension_id, company_id=resolved_company_id
        )
        if active_count > 0:
            raise BusinessException(
                message=(
                    "Cannot delete dimension with active KPI mappings. "
                    "Deactivate or remove mappings first."
                ),
                status_code=400,
            )

        await db.delete(dimension)
        await db.commit()
        return success_response(
            data={"id": dimension_id},
            message="Wellness dimension deleted successfully",
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | delete_dimension | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | delete_dimension | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to delete wellness dimension", status_code=500
        )
