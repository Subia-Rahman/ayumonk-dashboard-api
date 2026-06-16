from __future__ import annotations
"""HR analytics endpoints (CXO metrics by dept / age band).

Mounted under `/api/v1/hr/...` — separate prefix from `/dashboard/...` since
this is the HR Analytics console feed, not the per-user dashboard.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.cxo_metrics_dependencies import (
    CxoAccessContext,
    require_cxo_dashboard_access,
)
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.schemas.cxo_metrics import (
    HrCxoBucket,
    HrCxoMetricDefinition,
    HrCxoMetricResponse,
)
from config_service.app.services.hr_cxo_metrics import HrCxoMetricsService
from config_service.app.services.hr_filters import (
    HrFilters,
    hr_filters_from_query,
)


logger = get_file_logger(name="hr_analytics_api", prefix="hr_analytics_api")
router = APIRouter(prefix="/hr", tags=["hr-analytics"])


def _resolve_company_id(
    *, access: CxoAccessContext, company_id_param: UUID | None
) -> UUID:
    """Platform admins pass `company_id` explicitly; company-tier callers
    (admin/hr/cxo) are forced onto their own tenant — the query param is
    ignored. company_id is NEVER trusted from the request for non-platform
    callers."""
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


# ---------------------------------------------------------------------------
# GET /hr/cxo-metrics — aggregated CXO metric by dept + age_band in one payload
# ---------------------------------------------------------------------------


@router.get(
    "/cxo-metrics",
    response_model=APIResponse[HrCxoMetricResponse],
    summary="CXO metric aggregated by department and age band",
    description=(
        "Returns the weighted CXO metric per department and per age band for "
        "the caller's company. An employee is included only if they have "
        "scored every KPI mapped to the metric. The per-KPI score is "
        "normalized from the 1-5 form scale to 0-100 before weighting."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller cannot access this company"},
        404: {"description": "CXO metric not configured for this company"},
    },
)
async def get_cxo_metric(
    metric: str = Query(
        ..., description="Metric key — e.g. 'productivity' (case-insensitive)"
    ),
    company_id: UUID | None = Query(
        default=None,
        description=(
            "Required for platform admins; ignored for company-tier callers."
        ),
    ),
    filters: HrFilters = Depends(hr_filters_from_query),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_dashboard_access),
):
    logger.info(
        "REQUEST | hr_cxo_metric | user_id=%s | role=%s | metric=%s "
        "| company_id=%s | filters=%s",
        access.current_user.user_id,
        access.resolved_role,
        metric,
        company_id,
        filters,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        result = await HrCxoMetricsService(db).fetch_metric(
            metric=metric,
            company_id=resolved_company_id,
            filters=filters,
        )
        return success_response(
            data=HrCxoMetricResponse(
                metric=result["metric"],
                by_department=[HrCxoBucket(**b) for b in result["by_department"]],
                by_age_band=[HrCxoBucket(**b) for b in result["by_age_band"]],
            ),
            message="CXO metric fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | hr_cxo_metric | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | hr_cxo_metric | user_id=%s", access.current_user.user_id
        )
        return error_response(message="Failed to fetch CXO metric", status_code=500)


# ---------------------------------------------------------------------------
# GET /hr/cxo-metrics/definitions — drives the frontend toggle buttons
# ---------------------------------------------------------------------------


@router.get(
    "/cxo-metrics/definitions",
    response_model=APIResponse[list[HrCxoMetricDefinition]],
    summary="List available CXO metrics for the toggle buttons",
    description=(
        "Returns every CXO metric that has at least one active KPI mapping "
        "for the caller's company. `key` is lowercased to match the wire "
        "format the metric endpoint expects."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller cannot access this company"},
    },
)
async def list_cxo_metric_definitions(
    company_id: UUID | None = Query(
        default=None,
        description=(
            "Required for platform admins; ignored for company-tier callers."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_dashboard_access),
):
    logger.info(
        "REQUEST | hr_cxo_definitions | user_id=%s | role=%s | company_id=%s",
        access.current_user.user_id,
        access.resolved_role,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        rows = await HrCxoMetricsService(db).list_definitions(
            company_id=resolved_company_id
        )
        return success_response(
            data=[HrCxoMetricDefinition(**row) for row in rows],
            message="CXO metric definitions fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | hr_cxo_definitions | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | hr_cxo_definitions | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to fetch CXO metric definitions", status_code=500
        )
