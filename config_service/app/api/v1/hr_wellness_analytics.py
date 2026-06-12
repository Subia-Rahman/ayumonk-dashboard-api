"""HR Analytics — Wellness by Dimension and Gender-wise chart feeds.

All three endpoints live in a single router because they power one chart
section on the HR Analytics dashboard. Mounted at `/api/v1/hr/...` so the
gateway exposes them under `/config/api/v1/hr/...`.

Access: platform admins + company admin + HR + CXO — same role set as the
other HR Analytics endpoints (require_cxo_dashboard_access). Company-tier
callers (admin / hr / cxo) are forced onto their own tenant; platform admins
must pass `company_id` explicitly via query param.
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
from config_service.app.schemas.hr_wellness_analytics import (
    DimensionChartBucket,
    EmployeeCountResponse,
    GenderWellnessRow,
    HeadcountBucket,
    HeadcountResponse,
    HeatmapCell,
    HeatmapRow,
    HrCardValue,
    HrSummaryCardsResponse,
    WellnessByDimensionResponse,
    WellnessDimensionToggle,
    WellnessHeatmapResponse,
)
from config_service.app.services.hr_filters import (
    HrFilters,
    hr_filters_from_query,
)
from config_service.app.services.hr_wellness_analytics import (
    HrWellnessAnalyticsService,
)


logger = get_file_logger(
    name="hr_wellness_analytics_api", prefix="hr_wellness_analytics_api"
)
router = APIRouter(prefix="/hr", tags=["hr-analytics"])


def _resolve_company_id(
    *, access: CxoAccessContext, company_id_param: UUID | None
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


# ---------------------------------------------------------------------------
# GET /hr/wellness-dimensions — toggle definitions
# ---------------------------------------------------------------------------


@router.get(
    "/wellness-dimensions",
    response_model=APIResponse[list[WellnessDimensionToggle]],
    summary="List wellness dimension toggles for the chart header",
    description=(
        "Returns the toggle buttons to render above the Wellness by Dimension "
        "chart. `WellnessIndex` is hardcoded at `order=0`; the remaining "
        "entries come from the caller's company's `wellness_dimension` rows "
        "ordered by `display_order`."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller cannot access HR analytics"},
    },
)
async def list_wellness_dimensions(
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
        "REQUEST | list_wellness_dimensions | user_id=%s | role=%s | company_id=%s",
        access.current_user.user_id,
        access.resolved_role,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        rows = await HrWellnessAnalyticsService(db).list_dimension_toggles(
            company_id=resolved_company_id
        )
        return success_response(
            data=[WellnessDimensionToggle(**row) for row in rows],
            message="Wellness dimension toggles fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | list_wellness_dimensions | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | list_wellness_dimensions | user_id=%s",
            access.current_user.user_id,
        )
        return error_response(
            message="Failed to fetch wellness dimension toggles",
            status_code=500,
        )


# ---------------------------------------------------------------------------
# GET /hr/wellness-by-dimension — bar chart data
# ---------------------------------------------------------------------------


@router.get(
    "/wellness-by-dimension",
    response_model=APIResponse[WellnessByDimensionResponse],
    summary="Wellness scores grouped by department and location",
    description=(
        "Returns the average wellness score for the requested dimension, "
        "grouped by department and by location. `dimension=wellnessindex` "
        "reads the pre-computed wellness_index; any other value reads the "
        "KPI mapping for that dimension and computes a weighted score per "
        "employee (employees missing any mapped KPI are skipped)."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller cannot access HR analytics"},
        404: {"description": "Dimension is not configured"},
    },
)
async def wellness_by_dimension(
    dimension: str = Query(
        ...,
        description=(
            "Dimension key — 'wellnessindex' or one of the configured "
            "wellness_dimension keys (sleep, stress, nutrition, ...)."
        ),
        min_length=1,
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
        "REQUEST | wellness_by_dimension | user_id=%s | role=%s | dimension=%s "
        "| company_id=%s | filters=%s",
        access.current_user.user_id,
        access.resolved_role,
        dimension,
        company_id,
        filters,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        result = await HrWellnessAnalyticsService(db).wellness_by_dimension(
            dimension=dimension,
            company_id=resolved_company_id,
            filters=filters,
        )
        return success_response(
            data=WellnessByDimensionResponse(
                dimension=result["dimension"],
                by_department=[
                    DimensionChartBucket(**b) for b in result["by_department"]
                ],
                by_location=[
                    DimensionChartBucket(**b) for b in result["by_location"]
                ],
            ),
            message="Wellness by dimension fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | wellness_by_dimension | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | wellness_by_dimension | user_id=%s",
            access.current_user.user_id,
        )
        return error_response(
            message="Failed to fetch wellness by dimension", status_code=500
        )


# ---------------------------------------------------------------------------
# GET /hr/gender-wellness — horizontal bar chart data
# ---------------------------------------------------------------------------


@router.get(
    "/gender-wellness",
    response_model=APIResponse[list[GenderWellnessRow]],
    summary="Wellness + productivity scores grouped by gender",
    description=(
        "Returns wellness_score (always) and productivity_score (when the "
        "'productivity' dimension is configured; otherwise null) per gender. "
        "Genders are returned in Male / Female / Other order; genders with "
        "no employees are omitted."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller cannot access HR analytics"},
    },
)
async def gender_wellness(
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
        "REQUEST | gender_wellness | user_id=%s | role=%s | company_id=%s "
        "| filters=%s",
        access.current_user.user_id,
        access.resolved_role,
        company_id,
        filters,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        rows = await HrWellnessAnalyticsService(
            db
        ).gender_wellness_productivity(
            company_id=resolved_company_id, filters=filters
        )
        return success_response(
            data=[GenderWellnessRow(**row) for row in rows],
            message="Gender wellness fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | gender_wellness | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | gender_wellness | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to fetch gender wellness", status_code=500
        )


# ---------------------------------------------------------------------------
# GET /hr/heatmap/location-department — wellness heatmap grid
# ---------------------------------------------------------------------------


@router.get(
    "/heatmap/location-department",
    response_model=APIResponse[WellnessHeatmapResponse],
    summary="Location x Department wellness heatmap grid",
    description=(
        "Returns the 2D Wellness Index grid powering the Location x Department "
        "heatmap on the HR Analytics dashboard. Rows are unique employee "
        "locations, columns are unique departments, and each cell is the "
        "average wellness index (0-100, integer-rounded) of employees in that "
        "location AND that department. Empty intersections return value=null "
        "so the frontend receives a complete grid. Optional filters narrow the "
        "employee pool and (for date_from/date_to) the submission window used "
        "to resolve the latest response per employee."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller cannot access HR analytics"},
    },
)
async def wellness_heatmap_location_department(
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
        "REQUEST | wellness_heatmap_loc_dept | user_id=%s | role=%s "
        "| company_id=%s | filters=%s",
        access.current_user.user_id,
        access.resolved_role,
        company_id,
        filters,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        result = await HrWellnessAnalyticsService(
            db
        ).wellness_heatmap_location_department(
            company_id=resolved_company_id,
            filters=filters,
        )
        return success_response(
            data=WellnessHeatmapResponse(
                locations=result["locations"],
                departments=result["departments"],
                heatmap=[
                    HeatmapRow(
                        location=row["location"],
                        scores=[HeatmapCell(**cell) for cell in row["scores"]],
                    )
                    for row in result["heatmap"]
                ],
            ),
            message="Wellness heatmap fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | wellness_heatmap_loc_dept | %s", e.message)
        return error_response(
            message=e.message, status_code=e.status_code, errors=e.errors
        )
    except Exception:
        logger.exception(
            "ERROR | wellness_heatmap_loc_dept | user_id=%s",
            access.current_user.user_id,
        )
        return error_response(
            message="Failed to fetch wellness heatmap", status_code=500
        )


# ---------------------------------------------------------------------------
# GET /hr/summary-cards — six KPI cards on the HR Analytics dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/summary-cards",
    response_model=APIResponse[HrSummaryCardsResponse],
    summary="Six summary cards for the HR Analytics dashboard header",
    description=(
        "Returns the six KPI cards rendered above the HR Analytics dashboard: "
        "Avg Wellness, Productivity, Engagement, Absenteeism (days/month), "
        "Sleep Score (1-5), and Stress Score (1-5, display-inverted so a "
        "lower value reads as 'more stress'). Productivity, engagement, and "
        "absenteeism are derived from `wellness_dimension_kpi_mapping`; if a "
        "dimension isn't configured for the caller's company, that card's "
        "`value` is null but the rest of the response is unaffected."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller cannot access HR analytics"},
    },
)
async def hr_summary_cards(
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
        "REQUEST | hr_summary_cards | user_id=%s | role=%s "
        "| company_id=%s | filters=%s",
        access.current_user.user_id,
        access.resolved_role,
        company_id,
        filters,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        result = await HrWellnessAnalyticsService(db).summary_cards(
            company_id=resolved_company_id,
            filters=filters,
        )
        return success_response(
            data=HrSummaryCardsResponse(
                avg_wellness=HrCardValue(**result["avg_wellness"]),
                productivity=HrCardValue(**result["productivity"]),
                engagement=HrCardValue(**result["engagement"]),
                absenteeism=HrCardValue(**result["absenteeism"]),
                sleep_score=HrCardValue(**result["sleep_score"]),
                stress_score=HrCardValue(**result["stress_score"]),
            ),
            message="HR summary cards fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | hr_summary_cards | %s", e.message)
        return error_response(
            message=e.message, status_code=e.status_code, errors=e.errors
        )
    except Exception:
        logger.exception(
            "ERROR | hr_summary_cards | user_id=%s",
            access.current_user.user_id,
        )
        return error_response(
            message="Failed to fetch HR summary cards", status_code=500
        )


# ---------------------------------------------------------------------------
# GET /hr/employee-count — filter-aware "X of Y employees" badge
# ---------------------------------------------------------------------------


@router.get(
    "/employee-count",
    response_model=APIResponse[EmployeeCountResponse],
    summary="Filter-aware employee count for the HR Analytics filter strip",
    description=(
        "Returns both the unfiltered company headcount (`total`) and the "
        "count after applying the seven shared HR Analytics filters "
        "(`filtered`). The HR Analytics page renders these as "
        "`{filtered} of {total} employees in scope` next to the filter "
        "controls. Single round-trip via a COUNT(*) FILTER (...) so "
        "response time stays sub-100ms regardless of company size."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller cannot access HR analytics"},
    },
)
async def hr_employee_count(
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
        "REQUEST | hr_employee_count | user_id=%s | role=%s | company_id=%s "
        "| filters=%s",
        access.current_user.user_id,
        access.resolved_role,
        company_id,
        filters,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        result = await HrWellnessAnalyticsService(db).employee_count(
            company_id=resolved_company_id, filters=filters
        )
        return success_response(
            data=EmployeeCountResponse(
                total=result["total"], filtered=result["filtered"]
            ),
            message="Employee count fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | hr_employee_count | %s", e.message)
        return error_response(
            message=e.message, status_code=e.status_code, errors=e.errors
        )
    except Exception:
        logger.exception(
            "ERROR | hr_employee_count | user_id=%s",
            access.current_user.user_id,
        )
        return error_response(
            message="Failed to fetch employee count", status_code=500
        )


# ---------------------------------------------------------------------------
# GET /hr/headcount — per-dept + per-loc headcount (filter-narrowed)
# ---------------------------------------------------------------------------


@router.get(
    "/headcount",
    response_model=APIResponse[HeadcountResponse],
    summary="Filter-narrowed headcount per department and per location",
    description=(
        "Returns the filtered headcount broken down by department and by "
        "location. Used to size bubbles on the Wellness x Productivity "
        "scatter plot (bubble area proportional to dept headcount) and "
        "any other chart that needs to weight a series by headcount. "
        "Departments / locations with zero filtered employees are "
        "omitted from the response."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller cannot access HR analytics"},
    },
)
async def hr_headcount(
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
        "REQUEST | hr_headcount | user_id=%s | role=%s | company_id=%s "
        "| filters=%s",
        access.current_user.user_id,
        access.resolved_role,
        company_id,
        filters,
    )
    db.info["user_id"] = access.current_user.user_id

    try:
        resolved_company_id = _resolve_company_id(
            access=access, company_id_param=company_id
        )
        result = await HrWellnessAnalyticsService(db).headcount(
            company_id=resolved_company_id, filters=filters
        )
        return success_response(
            data=HeadcountResponse(
                by_department=[
                    HeadcountBucket(**b) for b in result["by_department"]
                ],
                by_location=[
                    HeadcountBucket(**b) for b in result["by_location"]
                ],
            ),
            message="Headcount fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | hr_headcount | %s", e.message)
        return error_response(
            message=e.message, status_code=e.status_code, errors=e.errors
        )
    except Exception:
        logger.exception(
            "ERROR | hr_headcount | user_id=%s",
            access.current_user.user_id,
        )
        return error_response(
            message="Failed to fetch headcount", status_code=500
        )
