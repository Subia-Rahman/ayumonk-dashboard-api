from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.core.rbac import require_permission
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.core.config import settings
from config_service.app.repositories.kpi import KPIRepository
from config_service.app.repositories.kpi_questions import KPIQuestionRepository
from config_service.app.repositories.kpi_scoring import KPIScoringRepository
from config_service.app.repositories.theme import ThemeRepository
from config_service.app.schemas.kpi_questions_admin import (
    KPIQuestionCreateRequest,
    KPIQuestionListResponse,
    KPIQuestionResponse,
    KPIQuestionUpdateRequest,
)
from config_service.app.services.kpi_questions_admin import KPIQuestionAdminService


logger = get_file_logger(name="kpi_question_admin_api", prefix="kpi_question_admin_api")
router = APIRouter(prefix="/kpi-questions", tags=["kpi-questions"])


async def _resolve_company_id(current_user, db: AsyncSession, company_id_param: UUID | None = None):
    if getattr(current_user, "is_platform_admin", False):
        return company_id_param
    tenant_id = getattr(current_user, "tenant_id", None)
    if tenant_id is None:
        raise BusinessException(message="Admin company not found", status_code=403)
    return tenant_id


@router.get("", response_model=APIResponse[KPIQuestionListResponse])
async def list_kpi_questions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    company_id: UUID | None = Query(default=None),
    kpi_key: UUID | None = None,
    theme_key: UUID | None = None,
    search: str | None = None,
    is_active: bool | None = True,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("kpis:read")),
):
    logger.info(
        "REQUEST | list_kpi_questions | user_id=%s | skip=%s | limit=%s | company_id=%s",
        current_user.user_id,
        skip,
        limit,
        company_id,
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        service = KPIQuestionAdminService(
            KPIQuestionRepository(db),
            KPIScoringRepository(db),
            ThemeRepository(db),
            KPIRepository(db),
        )
        result = await service.list(
            skip=skip,
            limit=limit,
            company_id=resolved,
            kpi_key=kpi_key,
            theme_key=theme_key,
            search=search,
            is_active=is_active,
        )
        return success_response(data=result, message="KPI questions fetched successfully")
    except BusinessException as e:
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception as e:
        logger.exception("ERROR | list_kpi_questions | user_id=%s", current_user.user_id)
        return error_response(
            message="Failed to fetch KPI questions",
            status_code=500,
            errors=str(e) if settings.DEBUG_ERRORS else None,
        )


@router.get("/{question_id}", response_model=APIResponse[KPIQuestionResponse])
async def get_kpi_question(
    question_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("kpis:read")),
):
    logger.info(
        "REQUEST | get_kpi_question | user_id=%s | question_id=%s",
        current_user.user_id,
        str(question_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = KPIQuestionAdminService(
            KPIQuestionRepository(db),
            KPIScoringRepository(db),
            ThemeRepository(db),
            KPIRepository(db),
        )
        result = await service.get(question_id)
        return success_response(data=result, message="KPI question fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_kpi_question | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_kpi_question | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch KPI question", status_code=500)


@router.post("", response_model=APIResponse[KPIQuestionResponse])
async def create_kpi_question(
    payload: KPIQuestionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("kpis:create")),
):
    logger.info("REQUEST | create_kpi_question | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        service = KPIQuestionAdminService(
            KPIQuestionRepository(db),
            KPIScoringRepository(db),
            ThemeRepository(db),
            KPIRepository(db),
        )
        result = await service.create(payload)
        return success_response(data=result, message="KPI question created successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | create_kpi_question | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_kpi_question | %s", e.errors())
        return error_response(message="Invalid KPI question payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | create_kpi_question | user_id=%s", current_user.user_id)
        return error_response(message="Failed to create KPI question", status_code=500)


@router.put("/{question_id}", response_model=APIResponse[KPIQuestionResponse])
async def update_kpi_question(
    question_id: UUID,
    payload: KPIQuestionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("kpis:update")),
):
    logger.info(
        "REQUEST | update_kpi_question | user_id=%s | question_id=%s",
        current_user.user_id,
        str(question_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = KPIQuestionAdminService(
            KPIQuestionRepository(db),
            KPIScoringRepository(db),
            ThemeRepository(db),
            KPIRepository(db),
        )
        result = await service.update(question_id, payload)
        return success_response(data=result, message="KPI question updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_kpi_question | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_kpi_question | %s", e.errors())
        return error_response(message="Invalid KPI question payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | update_kpi_question | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update KPI question", status_code=500)


@router.delete("/{question_id}", response_model=APIResponse[KPIQuestionResponse])
async def delete_kpi_question(
    question_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("kpis:delete")),
):
    logger.info(
        "REQUEST | delete_kpi_question | user_id=%s | question_id=%s",
        current_user.user_id,
        str(question_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = KPIQuestionAdminService(
            KPIQuestionRepository(db),
            KPIScoringRepository(db),
            ThemeRepository(db),
            KPIRepository(db),
        )
        result = await service.delete(question_id)
        return success_response(data=result, message="KPI question deleted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_kpi_question | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_kpi_question | user_id=%s", current_user.user_id)
        return error_response(message="Failed to delete KPI question", status_code=500)
