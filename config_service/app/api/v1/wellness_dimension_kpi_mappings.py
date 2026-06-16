from __future__ import annotations
"""CRUD endpoints for `wellness_dimension_kpi_mapping` — per-dimension KPI
weights, tenant-scoped via the parent dimension's `company_id`.

Routes are nested under `/dimensions/{dimension_id}/mappings`, mounted by the
gateway at `/config/api/v1/dimensions/{dimension_id}/mappings/...`.

Tenant scoping:
  * Platform admin (Super Admin / Ayumonk Admin) — passes the target
    `company_id` via query param.
  * Company admin / HR — forced onto their own tenant; the query param is
    ignored if supplied. Returns 404 if `dimension_id` does not belong to
    their tenant.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from pydantic import ValidationError
from sqlalchemy import select
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
from config_service.app.models.kpi import KPI
from config_service.app.models.wellness_dimensions import (
    WellnessDimension,
    WellnessDimensionKpiMapping,
)
from config_service.app.repositories.wellness_dimensions import (
    WellnessDimensionKpiMappingRepository,
    WellnessDimensionRepository,
)
from config_service.app.schemas.wellness_dimensions import (
    DimensionKpiMappingCreateRequest,
    DimensionKpiMappingListResponse,
    DimensionKpiMappingResponse,
    DimensionKpiMappingUpdateRequest,
)


logger = get_file_logger(
    name="dimension_kpi_mappings_api", prefix="dimension_kpi_mappings_api"
)
router = APIRouter(
    prefix="/dimensions/{dimension_id}/mappings",
    tags=["wellness-dimension-kpi-mappings"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_company_id(
    *, access: DimensionAccessContext, company_id_param: UUID | None
) -> UUID:
    """Platform admins must pass `company_id`; company-tier callers are
    forced onto their own tenant. company_id is NEVER trusted from the
    request for non-platform callers."""
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
    mapping: WellnessDimensionKpiMapping,
    display_name: str | None,
    wi_weight,
) -> DimensionKpiMappingResponse:
    return DimensionKpiMappingResponse(
        id=mapping.id,
        company_id=mapping.company_id,
        dimension_id=mapping.dimension_id,
        kpi_key=mapping.kpi_key,
        display_name=display_name,
        wi_weight=wi_weight,
        weight=mapping.weight,
        display_order=int(mapping.display_order),
        is_active=bool(mapping.is_active),
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
        created_by=mapping.created_by,
        updated_by=mapping.updated_by,
    )


async def _get_dimension_for_tenant(
    db: AsyncSession, *, dimension_id: int, company_id: UUID
) -> WellnessDimension:
    """Fetch the dimension scoped to the resolved company. Raises 404 if the
    dimension does not exist within the tenant."""
    dimension = await WellnessDimensionRepository(db).get_by_id(
        dimension_id, company_id=company_id
    )
    if dimension is None:
        raise BusinessException(
            message=f"Wellness dimension {dimension_id} not found",
            status_code=404,
        )
    return dimension


async def _assert_kpi_active(
    db: AsyncSession, kpi_key: UUID, *, company_id: UUID
) -> KPI:
    """Validate that `kpi_key` exists in the KPI catalog, is active, and is
    visible to this tenant (global KPIs have `company_id IS NULL`; per-company
    KPIs must match the caller's company)."""
    stmt = select(KPI).where(
        KPI.kpi_key == kpi_key,
        KPI.is_deleted == False,  # noqa: E712
        ((KPI.company_id == company_id) | (KPI.company_id.is_(None))),
    )
    kpi = (await db.execute(stmt)).scalar_one_or_none()
    if kpi is None or not kpi.is_active:
        raise BusinessException(
            message=f"KPI '{kpi_key}' not found or inactive",
            status_code=400,
        )
    return kpi


# ---------------------------------------------------------------------------
# GET — list mappings for a dimension
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=APIResponse[DimensionKpiMappingListResponse],
    summary="List KPI mappings for a wellness dimension",
    description=(
        "Returns every mapping row (active and inactive) for the supplied "
        "dimension, joined with the KPI catalog to include `display_name` and "
        "`wi_weight`."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller's role cannot access this endpoint"},
        404: {"description": "Dimension not found for this tenant"},
    },
)
async def list_dimension_mappings(
    dimension_id: int = Path(..., ge=1),
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
        "REQUEST | list_dimension_mappings | user_id=%s | dimension_id=%s | company_id=%s",
        access.current_user.user_id,
        dimension_id,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        await _get_dimension_for_tenant(
            db, dimension_id=dimension_id, company_id=resolved_company_id
        )
        rows = await WellnessDimensionKpiMappingRepository(
            db
        ).list_for_dimension_with_kpi(
            dimension_id, company_id=resolved_company_id
        )
        return success_response(
            data=DimensionKpiMappingListResponse(
                items=[
                    _to_response(mapping, display_name, wi_weight)
                    for mapping, display_name, wi_weight in rows
                ]
            ),
            message="Dimension KPI mappings fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | list_dimension_mappings | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | list_dimension_mappings | user_id=%s",
            access.current_user.user_id,
        )
        return error_response(
            message="Failed to fetch dimension KPI mappings", status_code=500
        )


# ---------------------------------------------------------------------------
# POST — add a KPI to a dimension
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=APIResponse[DimensionKpiMappingResponse],
    summary="Add a KPI to a wellness dimension",
    description=(
        "Creates a new `wellness_dimension_kpi_mapping` row stamped with the "
        "parent dimension's `company_id`. Fails with 400 if the KPI is "
        "missing/inactive, the weight is not strictly positive, or a mapping "
        "for the same (dimension, kpi) already exists."
    ),
    responses={
        400: {
            "description": (
                "KPI not found/inactive, weight ≤ 0, duplicate mapping, or "
                "company_id missing for a platform admin"
            )
        },
        403: {"description": "Caller's role cannot access this endpoint"},
        404: {"description": "Dimension not found or inactive for this tenant"},
    },
)
async def create_dimension_mapping(
    payload: DimensionKpiMappingCreateRequest,
    dimension_id: int = Path(..., ge=1),
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
        "REQUEST | create_dimension_mapping | user_id=%s | dimension_id=%s | kpi_key=%s | company_id=%s",
        access.current_user.user_id,
        dimension_id,
        payload.kpi_key,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        dimension = await _get_dimension_for_tenant(
            db, dimension_id=dimension_id, company_id=resolved_company_id
        )
        if not dimension.is_active:
            raise BusinessException(
                message=f"Wellness dimension {dimension_id} is not active",
                status_code=404,
            )

        if payload.weight is None or payload.weight <= Decimal("0"):
            raise BusinessException(
                message="Weight must be greater than 0", status_code=400
            )

        kpi = await _assert_kpi_active(
            db, payload.kpi_key, company_id=resolved_company_id
        )

        mapping_repo = WellnessDimensionKpiMappingRepository(db)
        existing = await mapping_repo.get_by_dimension_and_kpi(
            dimension_id, payload.kpi_key, company_id=resolved_company_id
        )
        if existing is not None:
            raise BusinessException(
                message=(
                    f"KPI '{payload.kpi_key}' is already mapped to this dimension"
                ),
                status_code=400,
            )

        mapping = WellnessDimensionKpiMapping(
            company_id=resolved_company_id,
            dimension_id=dimension_id,
            kpi_key=payload.kpi_key,
            weight=payload.weight,
            display_order=payload.display_order,
            is_active=payload.is_active,
            is_deleted=False,
        )
        db.add(mapping)
        await db.flush()
        await db.refresh(mapping)
        await db.commit()
        return success_response(
            data=_to_response(mapping, kpi.display_name, kpi.wi_weight),
            message="Dimension KPI mapping created successfully",
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | create_dimension_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        await db.rollback()
        logger.warning("VALIDATION_ERROR | create_dimension_mapping | %s", e.errors())
        return error_response(
            message="Invalid dimension KPI mapping payload",
            status_code=422,
            errors=e.errors(),
        )
    except IntegrityError:
        await db.rollback()
        logger.warning(
            "INTEGRITY_ERROR | create_dimension_mapping | dimension_id=%s | kpi_key=%s",
            dimension_id,
            payload.kpi_key,
        )
        return error_response(
            message=(
                f"KPI '{payload.kpi_key}' is already mapped to this dimension"
            ),
            status_code=400,
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | create_dimension_mapping | user_id=%s",
            access.current_user.user_id,
        )
        return error_response(
            message="Failed to create dimension KPI mapping", status_code=500
        )


# ---------------------------------------------------------------------------
# PATCH — update a mapping (weight / display_order / is_active)
# ---------------------------------------------------------------------------


@router.patch(
    "/{mapping_id}",
    response_model=APIResponse[DimensionKpiMappingResponse],
    summary="Update a dimension KPI mapping",
    description=(
        "Partial update — only the supplied fields are applied. `kpi_key` and "
        "`dimension_id` are immutable; delete and re-create to change them."
    ),
    responses={
        400: {
            "description": (
                "Invalid update (weight ≤ 0) or company_id missing for a "
                "platform admin"
            )
        },
        403: {"description": "Caller's role cannot access this endpoint"},
        404: {"description": "Mapping not found for this dimension/tenant"},
    },
)
async def update_dimension_mapping(
    payload: DimensionKpiMappingUpdateRequest,
    dimension_id: int = Path(..., ge=1),
    mapping_id: int = Path(..., ge=1),
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
        "REQUEST | update_dimension_mapping | user_id=%s | dimension_id=%s | mapping_id=%s | company_id=%s",
        access.current_user.user_id,
        dimension_id,
        mapping_id,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        mapping_repo = WellnessDimensionKpiMappingRepository(db)
        mapping = await mapping_repo.get_by_id(
            mapping_id, company_id=resolved_company_id
        )
        if mapping is None or mapping.dimension_id != dimension_id:
            raise BusinessException(
                message=(
                    f"Dimension KPI mapping {mapping_id} not found for dimension "
                    f"{dimension_id}"
                ),
                status_code=404,
            )

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise BusinessException(
                message="No updatable fields supplied", status_code=400
            )

        if "weight" in updates:
            new_weight = updates["weight"]
            if new_weight is None or Decimal(new_weight) <= Decimal("0"):
                raise BusinessException(
                    message="Weight must be greater than 0", status_code=400
                )

        for field, value in updates.items():
            setattr(mapping, field, value)
        mapping.updated_at = datetime.utcnow()

        await db.commit()
        await db.refresh(mapping)

        kpi_row = (
            await db.execute(
                select(KPI.display_name, KPI.wi_weight).where(
                    KPI.kpi_key == mapping.kpi_key
                )
            )
        ).first()
        display_name = kpi_row[0] if kpi_row else None
        wi_weight = kpi_row[1] if kpi_row else None

        return success_response(
            data=_to_response(mapping, display_name, wi_weight),
            message="Dimension KPI mapping updated successfully",
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | update_dimension_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        await db.rollback()
        logger.warning("VALIDATION_ERROR | update_dimension_mapping | %s", e.errors())
        return error_response(
            message="Invalid dimension KPI mapping payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | update_dimension_mapping | user_id=%s",
            access.current_user.user_id,
        )
        return error_response(
            message="Failed to update dimension KPI mapping", status_code=500
        )


# ---------------------------------------------------------------------------
# DELETE — hard-delete a mapping row
# ---------------------------------------------------------------------------


@router.delete(
    "/{mapping_id}",
    response_model=APIResponse[dict],
    summary="Delete a dimension KPI mapping",
    description=(
        "Hard-deletes the mapping row. No dependency checks — mappings can "
        "always be removed."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller's role cannot access this endpoint"},
        404: {"description": "Mapping not found for this dimension/tenant"},
    },
)
async def delete_dimension_mapping(
    dimension_id: int = Path(..., ge=1),
    mapping_id: int = Path(..., ge=1),
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
        "REQUEST | delete_dimension_mapping | user_id=%s | dimension_id=%s | mapping_id=%s | company_id=%s",
        access.current_user.user_id,
        dimension_id,
        mapping_id,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        mapping_repo = WellnessDimensionKpiMappingRepository(db)
        mapping = await mapping_repo.get_by_id(
            mapping_id, company_id=resolved_company_id
        )
        if mapping is None or mapping.dimension_id != dimension_id:
            raise BusinessException(
                message=(
                    f"Dimension KPI mapping {mapping_id} not found for dimension "
                    f"{dimension_id}"
                ),
                status_code=404,
            )

        await db.delete(mapping)
        await db.commit()
        return success_response(
            data={"id": mapping_id},
            message="Dimension KPI mapping deleted successfully",
        )
    except BusinessException as e:
        await db.rollback()
        logger.warning("BUSINESS_ERROR | delete_dimension_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        await db.rollback()
        logger.exception(
            "ERROR | delete_dimension_mapping | user_id=%s",
            access.current_user.user_id,
        )
        return error_response(
            message="Failed to delete dimension KPI mapping", status_code=500
        )
