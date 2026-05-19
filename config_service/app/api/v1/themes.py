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
from config_service.app.repositories.theme import ThemeRepository
from config_service.app.schemas.theme import (
    ThemeCreateRequest,
    ThemeListResponse,
    ThemeResponse,
    ThemeUpdateRequest,
)
from config_service.app.services.theme import ThemeService


logger = get_file_logger(name="theme_api", prefix="theme_api")
router = APIRouter(prefix="/themes", tags=["themes"])


async def _resolve_company_id(current_user, db: AsyncSession, company_id_param: UUID | None = None):
    if getattr(current_user, "is_platform_admin", False):
        return company_id_param
    tenant_id = getattr(current_user, "tenant_id", None)
    if tenant_id is None:
        raise BusinessException(message="Admin company not found", status_code=403)
    return tenant_id


@router.get("", response_model=APIResponse[ThemeListResponse])
async def list_themes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    search: str | None = None,
    is_active: bool | None = True,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("themes:read")),
):
    logger.info(
        "REQUEST | list_themes | user_id=%s | skip=%s | limit=%s | active=%s",
        current_user.user_id, skip, limit, is_active,
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        service = ThemeService(ThemeRepository(db))
        result = await service.list(skip=skip, limit=limit, company_id=resolved, search=search, is_active=is_active)
        return success_response(data=result, message="Themes fetched successfully")
    except BusinessException as e:
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | list_themes | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch themes", status_code=500)


@router.get("/{theme_key}", response_model=APIResponse[ThemeResponse])
async def get_theme(
    theme_key: UUID,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("themes:read")),
):
    logger.info("REQUEST | get_theme | user_id=%s | theme_key=%s", current_user.user_id, str(theme_key))
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        service = ThemeService(ThemeRepository(db))
        result = await service.get(theme_key, resolved)
        return success_response(data=result, message="Theme fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_theme | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_theme | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch theme", status_code=500)


@router.post("", response_model=APIResponse[ThemeResponse])
async def create_theme(
    payload: ThemeCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("themes:create")),
):
    logger.info("REQUEST | create_theme | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, payload.company_id)
        payload.company_id = resolved
        service = ThemeService(ThemeRepository(db))
        result = await service.create(payload)
        return success_response(data=result, message="Theme created successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | create_theme | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_theme | %s", e.errors())
        return error_response(message="Invalid theme payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | create_theme | user_id=%s", current_user.user_id)
        return error_response(message="Failed to create theme", status_code=500)


@router.put("/{theme_key}", response_model=APIResponse[ThemeResponse])
async def update_theme(
    theme_key: UUID,
    payload: ThemeUpdateRequest,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("themes:update")),
):
    logger.info("REQUEST | update_theme | user_id=%s | theme_key=%s", current_user.user_id, str(theme_key))
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        service = ThemeService(ThemeRepository(db))
        result = await service.update(theme_key, payload, resolved)
        return success_response(data=result, message="Theme updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_theme | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_theme | %s", e.errors())
        return error_response(message="Invalid theme payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | update_theme | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update theme", status_code=500)


@router.delete("/{theme_key}", response_model=APIResponse[ThemeResponse])
async def delete_theme(
    theme_key: UUID,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("themes:delete")),
):
    logger.info("REQUEST | delete_theme | user_id=%s | theme_key=%s", current_user.user_id, str(theme_key))
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        service = ThemeService(ThemeRepository(db))
        result = await service.delete(theme_key, resolved)
        return success_response(data=result, message="Theme deleted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_theme | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_theme | user_id=%s", current_user.user_id)
        return error_response(message="Failed to delete theme", status_code=500)
