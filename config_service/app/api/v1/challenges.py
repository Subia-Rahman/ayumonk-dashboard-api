from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import require_roles
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.repositories.challenge import ChallengeRepository
from config_service.app.repositories.kpi import KPIRepository
from config_service.app.repositories.kpi_challenge import KPIChallengeRepository
from config_service.app.schemas.challenge import (
    ChallengeCreateRequest,
    ChallengeDetailResponse,
    ChallengeKPIMappingRequest,
    ChallengeKPIMappingResponse,
    ChallengeListResponse,
    ChallengeResponse,
    ChallengeUpdateRequest,
)
from config_service.app.services.challenge import ChallengeService


logger = get_file_logger(name="challenge_api", prefix="challenge_api")
router = APIRouter(prefix="/challenges", tags=["challenges"])


@router.get("", response_model=APIResponse[ChallengeListResponse])
async def list_challenges(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    search: str | None = None,
    is_active: bool | None = True,
    kpi_key: UUID | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("ADMIN")),
):
    logger.info(
        "REQUEST | list_challenges | user_id=%s | skip=%s | limit=%s | active=%s | kpi_key=%s | start=%s | end=%s",
        current_user.user_id,
        skip,
        limit,
        is_active,
        str(kpi_key) if kpi_key else None,
        start_date,
        end_date,
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = ChallengeService(
            ChallengeRepository(db),
            KPIRepository(db),
            KPIChallengeRepository(db),
        )
        result = await service.list(
            skip=skip,
            limit=limit,
            search=search,
            is_active=is_active,
            kpi_key=kpi_key,
            start_date=start_date,
            end_date=end_date,
        )
        return success_response(data=result, message="Challenges fetched successfully")
    except Exception:
        logger.exception("ERROR | list_challenges | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch challenges", status_code=500)


@router.get("/{challenge_key}", response_model=APIResponse[ChallengeDetailResponse])
async def get_challenge(
    challenge_key: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("ADMIN")),
):
    logger.info(
        "REQUEST | get_challenge | user_id=%s | challenge_key=%s",
        current_user.user_id,
        str(challenge_key),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = ChallengeService(
            ChallengeRepository(db),
            KPIRepository(db),
            KPIChallengeRepository(db),
        )
        result = await service.get(challenge_key)
        return success_response(data=result, message="Challenge fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_challenge | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_challenge | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch challenge", status_code=500)


@router.post("", response_model=APIResponse[ChallengeDetailResponse])
async def create_challenge(
    payload: ChallengeCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("ADMIN")),
):
    logger.info("REQUEST | create_challenge | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        service = ChallengeService(
            ChallengeRepository(db),
            KPIRepository(db),
            KPIChallengeRepository(db),
        )
        result = await service.create(payload)
        return success_response(data=result, message="Challenge created successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | create_challenge | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_challenge | %s", e.errors())
        return error_response(
            message="Invalid challenge payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        logger.exception("ERROR | create_challenge | user_id=%s", current_user.user_id)
        return error_response(message="Failed to create challenge", status_code=500)


@router.put("/{challenge_key}", response_model=APIResponse[ChallengeResponse])
async def update_challenge(
    challenge_key: UUID,
    payload: ChallengeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("ADMIN")),
):
    logger.info(
        "REQUEST | update_challenge | user_id=%s | challenge_key=%s",
        current_user.user_id,
        str(challenge_key),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = ChallengeService(
            ChallengeRepository(db),
            KPIRepository(db),
            KPIChallengeRepository(db),
        )
        result = await service.update(challenge_key, payload)
        return success_response(data=result, message="Challenge updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_challenge | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_challenge | %s", e.errors())
        return error_response(
            message="Invalid challenge payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        logger.exception("ERROR | update_challenge | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update challenge", status_code=500)


@router.delete("/{challenge_key}", response_model=APIResponse[ChallengeResponse])
async def delete_challenge(
    challenge_key: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("ADMIN")),
):
    logger.info(
        "REQUEST | delete_challenge | user_id=%s | challenge_key=%s",
        current_user.user_id,
        str(challenge_key),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = ChallengeService(
            ChallengeRepository(db),
            KPIRepository(db),
            KPIChallengeRepository(db),
        )
        result = await service.delete(challenge_key)
        return success_response(data=result, message="Challenge deleted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_challenge | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_challenge | user_id=%s", current_user.user_id)
        return error_response(message="Failed to delete challenge", status_code=500)




@router.post("/{challenge_key}/kpi-mappings", response_model=APIResponse[ChallengeKPIMappingResponse])
async def add_kpi_mapping(
    challenge_key: UUID,
    payload: ChallengeKPIMappingRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("ADMIN")),
):
    logger.info(
        "REQUEST | add_kpi_mapping | user_id=%s | challenge_key=%s",
        current_user.user_id,
        str(challenge_key),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = ChallengeService(
            ChallengeRepository(db),
            KPIRepository(db),
            KPIChallengeRepository(db),
        )
        result = await service.add_kpi_mapping(challenge_key=challenge_key, mapping=payload)
        return success_response(data=result, message="KPI mapping added successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | add_kpi_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | add_kpi_mapping | %s", e.errors())
        return error_response(
            message="Invalid KPI mapping payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        logger.exception("ERROR | add_kpi_mapping | user_id=%s", current_user.user_id)
        return error_response(message="Failed to add KPI mapping", status_code=500)
