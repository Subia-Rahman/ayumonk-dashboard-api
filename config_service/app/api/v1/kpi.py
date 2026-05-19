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
from config_service.app.repositories.company_users import UserRepository
from config_service.app.repositories.kpi import KPIRepository
from config_service.app.schemas.kpi import (
    KPICreateRequest,
    KPIListResponse,
    KPIResponse,
    KPIUpdateRequest,
)
from config_service.app.services.kpi import KPIService


logger = get_file_logger(name="kpi_api", prefix="kpi_api")
router = APIRouter(prefix="/kpi", tags=["kpi"])


async def _resolve_company_id(current_user, db: AsyncSession, company_id_param: UUID | None = None):
    if getattr(current_user, "is_platform_admin", False):
        return company_id_param
    tenant_id = getattr(current_user, "tenant_id", None)
    if tenant_id is None:
        raise BusinessException(message="Admin company not found", status_code=403)
    return tenant_id


@router.get("", response_model=APIResponse[KPIListResponse])
async def list_kpis(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    theme_key: UUID | None = None,
    search: str | None = None,
    is_active: bool | None = True,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("kpis:read")),
):
    logger.info(
        "REQUEST | list_kpis | user_id=%s | skip=%s | limit=%s | theme=%s | active=%s",
        current_user.user_id, skip, limit,
        str(theme_key) if theme_key else None, is_active,
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        service = KPIService(KPIRepository(db))
        result = await service.list(
            skip=skip, limit=limit, company_id=resolved,
            theme_key=theme_key, search=search, is_active=is_active,
        )
        return success_response(data=result, message="KPIs fetched successfully")
    except BusinessException as e:
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | list_kpis | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch KPIs", status_code=500)


@router.get("/{kpi_key}", response_model=APIResponse[KPIResponse])
async def get_kpi(
    kpi_key: UUID,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("kpis:read")),
):
    logger.info("REQUEST | get_kpi | user_id=%s | kpi_key=%s", current_user.user_id, str(kpi_key))
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        service = KPIService(KPIRepository(db))
        result = await service.get(kpi_key, resolved)
        return success_response(data=result, message="KPI fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_kpi | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_kpi | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch KPI", status_code=500)


@router.post("", response_model=APIResponse[KPIResponse])
async def create_kpi(
    payload: KPICreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("kpis:create")),
):
    logger.info("REQUEST | create_kpi | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, payload.company_id)
        payload.company_id = resolved
        service = KPIService(KPIRepository(db))
        result = await service.create(payload)
        return success_response(data=result, message="KPI created successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | create_kpi | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_kpi | %s", e.errors())
        return error_response(message="Invalid KPI payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | create_kpi | user_id=%s", current_user.user_id)
        return error_response(message="Failed to create KPI", status_code=500)


@router.put("/{kpi_key}", response_model=APIResponse[KPIResponse])
async def update_kpi(
    kpi_key: UUID,
    payload: KPIUpdateRequest,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("kpis:update")),
):
    logger.info("REQUEST | update_kpi | user_id=%s | kpi_key=%s", current_user.user_id, str(kpi_key))
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        service = KPIService(KPIRepository(db))
        result = await service.update(kpi_key, payload, resolved)
        return success_response(data=result, message="KPI updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_kpi | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_kpi | %s", e.errors())
        return error_response(message="Invalid KPI payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | update_kpi | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update KPI", status_code=500)


@router.delete("/{kpi_key}", response_model=APIResponse[KPIResponse])
async def delete_kpi(
    kpi_key: UUID,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("kpis:delete")),
):
    logger.info("REQUEST | delete_kpi | user_id=%s | kpi_key=%s", current_user.user_id, str(kpi_key))
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        service = KPIService(KPIRepository(db))
        result = await service.delete(kpi_key, resolved)
        return success_response(data=result, message="KPI deleted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_kpi | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_kpi | user_id=%s", current_user.user_id)
        return error_response(message="Failed to delete KPI", status_code=500)
