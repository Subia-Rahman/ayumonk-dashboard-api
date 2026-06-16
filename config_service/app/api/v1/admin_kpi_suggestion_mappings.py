from __future__ import annotations
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
from config_service.app.repositories.kpi import KPIRepository
from config_service.app.repositories.kpi_questions import KPIQuestionRepository
from config_service.app.repositories.kpi_suggestion_mappings import KPISuggestionMappingRepository
from config_service.app.repositories.suggestions import SuggestionRepository
from config_service.app.schemas.kpi_suggestion_mappings import (
    KPISuggestionMappingCreateRequest,
    KPISuggestionMappingListResponse,
    KPISuggestionMappingResponse,
    KPISuggestionMappingUpdateRequest,
)
from config_service.app.services.kpi_suggestion_mappings import KPISuggestionMappingService


logger = get_file_logger(name="admin_kpi_suggestion_api", prefix="admin_kpi_suggestion_api")
router = APIRouter(prefix="/admin/kpi-suggestion-mappings", tags=["admin-kpi-suggestion-mappings"])


@router.post("", response_model=APIResponse[KPISuggestionMappingResponse])
async def create_kpi_suggestion_mapping(
    payload: KPISuggestionMappingCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("suggestion:create")),
):
    logger.info("REQUEST | create_kpi_suggestion_mapping | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        service = KPISuggestionMappingService(
            KPISuggestionMappingRepository(db),
            KPIRepository(db),
            KPIQuestionRepository(db),
            SuggestionRepository(db),
        )
        result = await service.create(payload)
        return success_response(data=result, message="KPI suggestion mapping created successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | create_kpi_suggestion_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_kpi_suggestion_mapping | %s", e.errors())
        return error_response(
            message="Invalid KPI suggestion mapping payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        logger.exception("ERROR | create_kpi_suggestion_mapping | user_id=%s", current_user.user_id)
        return error_response(message="Failed to create KPI suggestion mapping", status_code=500)


@router.get("", response_model=APIResponse[KPISuggestionMappingListResponse])
async def list_kpi_suggestion_mappings(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    kpi_key: UUID | None = None,
    suggestion_id: UUID | None = None,
    trigger_mode: str | None = None,
    is_active: bool | None = True,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("suggestion:read")),
):
    logger.info(
        "REQUEST | list_kpi_suggestion_mappings | user_id=%s | skip=%s | limit=%s",
        current_user.user_id,
        skip,
        limit,
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = KPISuggestionMappingService(
            KPISuggestionMappingRepository(db),
            KPIRepository(db),
            KPIQuestionRepository(db),
            SuggestionRepository(db),
        )
        result = await service.list(
            skip=skip,
            limit=limit,
            kpi_key=kpi_key,
            suggestion_id=suggestion_id,
            trigger_mode=trigger_mode,
            is_active=is_active,
        )
        return success_response(data=result, message="KPI suggestion mappings fetched successfully")
    except Exception:
        logger.exception("ERROR | list_kpi_suggestion_mappings | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch KPI suggestion mappings", status_code=500)


@router.get("/{mapping_id}", response_model=APIResponse[KPISuggestionMappingResponse])
async def get_kpi_suggestion_mapping(
    mapping_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("suggestion:read")),
):
    logger.info(
        "REQUEST | get_kpi_suggestion_mapping | user_id=%s | mapping_id=%s",
        current_user.user_id,
        str(mapping_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = KPISuggestionMappingService(
            KPISuggestionMappingRepository(db),
            KPIRepository(db),
            KPIQuestionRepository(db),
            SuggestionRepository(db),
        )
        result = await service.get(mapping_id)
        return success_response(data=result, message="KPI suggestion mapping fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_kpi_suggestion_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_kpi_suggestion_mapping | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch KPI suggestion mapping", status_code=500)


@router.put("/{mapping_id}", response_model=APIResponse[KPISuggestionMappingResponse])
async def update_kpi_suggestion_mapping(
    mapping_id: UUID,
    payload: KPISuggestionMappingUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("suggestion:update")),
):
    logger.info(
        "REQUEST | update_kpi_suggestion_mapping | user_id=%s | mapping_id=%s",
        current_user.user_id,
        str(mapping_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = KPISuggestionMappingService(
            KPISuggestionMappingRepository(db),
            KPIRepository(db),
            KPIQuestionRepository(db),
            SuggestionRepository(db),
        )
        result = await service.update(mapping_id, payload)
        return success_response(data=result, message="KPI suggestion mapping updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_kpi_suggestion_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_kpi_suggestion_mapping | %s", e.errors())
        return error_response(
            message="Invalid KPI suggestion mapping payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        logger.exception("ERROR | update_kpi_suggestion_mapping | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update KPI suggestion mapping", status_code=500)


@router.delete("/{mapping_id}", response_model=APIResponse[KPISuggestionMappingResponse])
async def delete_kpi_suggestion_mapping(
    mapping_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("suggestion:delete")),
):
    logger.info(
        "REQUEST | delete_kpi_suggestion_mapping | user_id=%s | mapping_id=%s",
        current_user.user_id,
        str(mapping_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = KPISuggestionMappingService(
            KPISuggestionMappingRepository(db),
            KPIRepository(db),
            KPIQuestionRepository(db),
            SuggestionRepository(db),
        )
        result = await service.delete(mapping_id)
        return success_response(data=result, message="KPI suggestion mapping deleted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_kpi_suggestion_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_kpi_suggestion_mapping | user_id=%s", current_user.user_id)
        return error_response(message="Failed to delete KPI suggestion mapping", status_code=500)
