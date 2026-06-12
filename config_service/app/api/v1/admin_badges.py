from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.rbac import require_permission
from config_service.app.core.audit_helper import safe_audit_log
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.repositories.badge_master import BadgeMasterRepository
from config_service.app.schemas.badge_admin import (
    BadgeCreateRequest,
    BadgeListResponse,
    BadgeResponse,
    BadgeUpdateRequest,
)
from config_service.app.services.badge_admin import BadgeAdminService


logger = get_file_logger(name="admin_badges_api", prefix="admin_badges_api")
router = APIRouter(prefix="/badges", tags=["badges-admin"])


def _service(db: AsyncSession) -> BadgeAdminService:
    return BadgeAdminService(BadgeMasterRepository(db))


@router.get("", response_model=APIResponse[BadgeListResponse])
async def list_badges(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    kpi_key: UUID | None = Query(default=None, description="Filter to a specific KPI; omit to include all."),
    trigger_type: str | None = Query(default=None, regex="^(streak|kpi_completions|level)$"),
    level: str | None = Query(default=None, description="bronze | silver | gold | legend | platinum"),
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, description="Substring match against badge_key or label (case-insensitive)."),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("badges:read")),
):
    logger.info(
        "REQUEST | list_badges | user_id=%s | skip=%s limit=%s kpi=%s type=%s level=%s active=%s",
        current_user.user_id, skip, limit, str(kpi_key) if kpi_key else None,
        trigger_type, level, is_active,
    )
    db.info["user_id"] = current_user.user_id
    try:
        result = await _service(db).list(
            skip=skip, limit=limit, kpi_key=kpi_key,
            trigger_type=trigger_type, level=level,
            is_active=is_active, search=search,
        )
        return success_response(data=result, message="Badges fetched successfully")
    except BusinessException as e:
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | list_badges | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch badges", status_code=500)


@router.get("/{badge_id}", response_model=APIResponse[BadgeResponse])
async def get_badge(
    badge_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("badges:read")),
):
    logger.info("REQUEST | get_badge | user_id=%s | badge_id=%s", current_user.user_id, str(badge_id))
    db.info["user_id"] = current_user.user_id
    try:
        result = await _service(db).get(badge_id)
        return success_response(data=result, message="Badge fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_badge | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_badge | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch badge", status_code=500)


@router.post("", response_model=APIResponse[BadgeResponse])
async def create_badge(
    payload: BadgeCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("badges:create")),
):
    logger.info("REQUEST | create_badge | user_id=%s | badge_key=%s",
                current_user.user_id, payload.badge_key)
    db.info["user_id"] = current_user.user_id
    try:
        result = await _service(db).create(payload)
        await safe_audit_log(
            db,
            user_id=current_user.user_id,
            tenant_id=getattr(current_user, "tenant_id", None),
            action="BADGE_CREATED",
            entity="badges_master",
            new_value=result.model_dump(),
            logger=logger,
        )
        return success_response(data=result, message="Badge created successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | create_badge | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_badge | %s", e.errors())
        return error_response(message="Invalid badge payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | create_badge | user_id=%s", current_user.user_id)
        return error_response(message="Failed to create badge", status_code=500)


@router.put("/{badge_id}", response_model=APIResponse[BadgeResponse])
async def update_badge(
    badge_id: UUID,
    payload: BadgeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("badges:update")),
):
    logger.info("REQUEST | update_badge | user_id=%s | badge_id=%s",
                current_user.user_id, str(badge_id))
    db.info["user_id"] = current_user.user_id
    try:
        before = await _service(db).get(badge_id)
        result = await _service(db).update(badge_id, payload)
        await safe_audit_log(
            db,
            user_id=current_user.user_id,
            tenant_id=getattr(current_user, "tenant_id", None),
            action="BADGE_UPDATED",
            entity="badges_master",
            old_value=before.model_dump(),
            new_value=result.model_dump(),
            logger=logger,
        )
        return success_response(data=result, message="Badge updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_badge | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_badge | %s", e.errors())
        return error_response(message="Invalid badge payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | update_badge | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update badge", status_code=500)


@router.delete("/{badge_id}", response_model=APIResponse[BadgeResponse])
async def delete_badge(
    badge_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("badges:delete")),
):
    logger.info("REQUEST | delete_badge | user_id=%s | badge_id=%s",
                current_user.user_id, str(badge_id))
    db.info["user_id"] = current_user.user_id
    try:
        before = await _service(db).get(badge_id)
        result = await _service(db).delete(badge_id)
        await safe_audit_log(
            db,
            user_id=current_user.user_id,
            tenant_id=getattr(current_user, "tenant_id", None),
            action="BADGE_DELETED",
            entity="badges_master",
            old_value=before.model_dump(),
            new_value={"id": before.id, "is_active": False, "is_deleted": True},
            logger=logger,
        )
        return success_response(data=result, message="Badge deleted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_badge | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_badge | user_id=%s", current_user.user_id)
        return error_response(message="Failed to delete badge", status_code=500)
