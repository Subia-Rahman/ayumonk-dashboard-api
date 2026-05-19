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
)
from config_service.app.services.challenge_actions import ChallengeActionService


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
        result = await service.get_kpi_cards(current_user.email)
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
