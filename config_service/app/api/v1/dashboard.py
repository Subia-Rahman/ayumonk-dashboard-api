from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import get_current_user
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.services.dashboard import DashboardService
from config_service.app.schemas.dashboard import KPIDashboardResponse
from config_service.app.schemas.wellness_trends import Period, WellnessTrendsResponse
from config_service.app.services.wellness_trends import WellnessTrendsService
from pydantic import ValidationError
from config_service.app.schemas.challenge_actions import (
    ChallengeActionRequest,
    ChallengeActionResponse,
    ChallengeUndoRequest,
    ChallengeUndoResponse,
)
from config_service.app.services.challenge_actions import ChallengeActionService
from config_service.app.schemas.badges import MyBadgesResponse
from config_service.app.services.badges import BadgesService
from config_service.app.schemas.leaderboard import WeeklyLeaderboardResponse
from config_service.app.services.leaderboard import LeaderboardService
from config_service.app.core.cxo_metrics_dependencies import (
    CxoAccessContext,
    require_cxo_dashboard_access,
)
from config_service.app.schemas.employee_snapshots import (
    EmployeeSnapshotMeta,
    EmployeeSnapshotResponse,
    EmployeeSnapshotRow,
)
from config_service.app.services.employee_snapshots import EmployeeSnapshotsService
from uuid import UUID


logger = get_file_logger(name="dashboard_api", prefix="dashboard_api")
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/kpis", response_model=APIResponse[KPIDashboardResponse])
async def get_kpi_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    logger.info("REQUEST | get_kpi_dashboard | user_id=%s | email=%s", current_user.user_id, current_user.email)
    db.info["user_id"] = current_user.user_id

    try:
        service = DashboardService(db)
        result = await service.get_kpi_cards(current_user.email, user_id=current_user.user_id)
        return success_response(data=result, message="KPI dashboard fetched successfully")
    except Exception:
        logger.exception("ERROR | get_kpi_dashboard | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch KPI dashboard", status_code=500)




@router.get("/wellness-trends", response_model=APIResponse[WellnessTrendsResponse])
async def get_wellness_trends(
    period: Period = Query(default="weekly"),
    bucket_count: int | None = Query(default=None, ge=2, le=24),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    logger.info(
        "REQUEST | get_wellness_trends | user_id=%s | period=%s | bucket_count=%s",
        current_user.user_id, period, bucket_count,
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = WellnessTrendsService(db)
        result = await service.get_trends(
            email=current_user.email,
            period=period,
            bucket_count=bucket_count,
        )
        return success_response(data=result, message="Wellness trends fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_wellness_trends | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_wellness_trends | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch wellness trends", status_code=500)


@router.post("/challenges/action", response_model=APIResponse[ChallengeActionResponse])
async def mark_challenge_action(
    payload: ChallengeActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    logger.info(
        "REQUEST | mark_challenge_action | user_id=%s | challenge_id=%s",
        current_user.user_id,
        str(payload.challenge_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = ChallengeActionService(db)
        result = await service.mark_challenge_done(
            user_id=current_user.user_id,
            user_email=current_user.email,
            payload=payload,
        )
        return success_response(data=result, message=result.message)
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | mark_challenge_action | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | mark_challenge_action | %s", e.errors())
        return error_response(message="Invalid challenge action payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | mark_challenge_action | user_id=%s", current_user.user_id)
        return error_response(message="Failed to mark challenge action", status_code=500)


@router.post("/challenges/undo", response_model=APIResponse[ChallengeUndoResponse])
async def undo_challenge_action(
    payload: ChallengeUndoRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Undo today's completion for a toggle-type challenge. Soft-deletes the
    UserChallengeCompletion row, deducts the XP that was awarded, and rewinds
    the streak by one day (last_completion_date moves back; longest_streak is
    preserved). Only `toggle` is supported — counter/timer/multi/choice/rating
    have no "uncheck" UX.
    """
    logger.info(
        "REQUEST | undo_challenge_action | user_id=%s | challenge_id=%s",
        current_user.user_id,
        str(payload.challenge_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = ChallengeActionService(db)
        result = await service.undo_toggle(
            user_id=current_user.user_id,
            user_email=current_user.email,
            challenge_id=payload.challenge_id,
        )
        return success_response(data=result, message=result.message)
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | undo_challenge_action | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | undo_challenge_action | %s", e.errors())
        return error_response(message="Invalid undo payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | undo_challenge_action | user_id=%s", current_user.user_id)
        return error_response(message="Failed to undo challenge action", status_code=500)


@router.get("/leaderboard", response_model=APIResponse[WeeklyLeaderboardResponse])
async def get_weekly_leaderboard(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Weekly Challenges-tab leaderboard for the requesting employee's company.
    Ranking is on `user_xp.xp_this_week` (Mon-Sun, reset by pg_cron); the
    `+42%`-style delta is computed against last week's XP summed from
    `user_challenge_completions`. company_id is taken from the JWT (never the
    query/body) so a caller can never read another tenant's board.
    """
    logger.info("REQUEST | get_weekly_leaderboard | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        service = LeaderboardService(db)
        result = await service.get_weekly_leaderboard(
            user_id=current_user.user_id,
            company_id=current_user.tenant_id,
        )
        return success_response(data=result, message="Leaderboard fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_weekly_leaderboard | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_weekly_leaderboard | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch leaderboard", status_code=500)


@router.get("/me/badges", response_model=APIResponse[MyBadgesResponse])
async def get_my_badges(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Returns every badge visible to the current user (global + own-company KPI
    badges) with earned/locked status, so the UI can render the badge cabinet
    with greyed-out tiles for locked badges.
    """
    logger.info("REQUEST | get_my_badges | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        service = BadgesService(db)
        result = await service.list_for_user(
            user_id=current_user.user_id,
            user_email=current_user.email,
        )
        return success_response(data=result, message="Badges fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_my_badges | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_my_badges | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch badges", status_code=500)


# -----------------------------------------------------------------------------
# Employee snapshots feed (HR_ROWS) — one row per active employee with all
# wellness/CXO metrics pre-computed. The HR Analytics dashboard does its own
# grouping/averaging client-side.
#
# Company-tier callers (admin / hr / cxo) are forced onto their own tenant —
# the query param is ignored. Platform admins must pass `company_id`.
# -----------------------------------------------------------------------------
@router.get(
    "/employee-snapshots",
    response_model=APIResponse[EmployeeSnapshotResponse],
    summary="Per-employee wellness + CXO snapshot feed",
    description=(
        "One row per active employee. Demographic fields come from "
        "`company_users` (+ `companies.location_id` for `loc` — every "
        "employee in a single-location company shares one value, surfaced as "
        "`meta.locationGranularity=\"company\"`). KPI columns (`sleep`, "
        "`stress`, `nutrition`) are pivoted by case-insensitive trimmed "
        "`kpis.display_name`. CXO columns (`productivity`, `engagement`, "
        "`absenteeism`) follow the per-company mapping rules. Metrics whose "
        "mapping is empty (or whose master row hasn't been seeded for this "
        "company) appear in `meta.missingMappings`; KPIs the company doesn't "
        "have appear in `meta.missingKpis`. Neither condition fails the "
        "request — the field is just `null` for affected employees."
    ),
    responses={
        400: {"description": "company_id missing for a platform admin"},
        403: {"description": "Caller cannot access this company"},
    },
)
async def get_employee_snapshots(
    company_id: UUID | None = Query(
        default=None,
        description=(
            "Required for platform admins; ignored for company-tier callers "
            "(forced to their own company)."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    access: CxoAccessContext = Depends(require_cxo_dashboard_access),
):
    logger.info(
        "REQUEST | employee_snapshots | user_id=%s | role=%s | company_id=%s",
        access.current_user.user_id,
        access.resolved_role,
        company_id,
    )
    db.info["user_id"] = access.current_user.user_id

    if access.is_platform_admin:
        if company_id is None:
            return error_response(
                message="company_id is required for platform admins",
                status_code=400,
            )
        resolved_company_id = company_id
    else:
        if access.tenant_id is None:
            return error_response(
                message="No tenant assignment on current user",
                status_code=403,
            )
        resolved_company_id = access.tenant_id

    try:
        result = await EmployeeSnapshotsService(db).fetch(
            company_id=resolved_company_id
        )
        return success_response(
            data=EmployeeSnapshotResponse(
                data=[EmployeeSnapshotRow(**row) for row in result["data"]],
                meta=EmployeeSnapshotMeta(**result["meta"]),
            ),
            message="Employee snapshots fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | employee_snapshots | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | employee_snapshots | user_id=%s", access.current_user.user_id
        )
        return error_response(
            message="Failed to fetch employee snapshots", status_code=500
        )
