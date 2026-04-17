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
from config_service.app.repositories.suggestions import SuggestionRepository
from config_service.app.schemas.suggestions import (
    SuggestionCreateRequest,
    SuggestionListResponse,
    SuggestionResponse,
    SuggestionUpdateRequest,
)
from config_service.app.services.suggestions import SuggestionService


logger = get_file_logger(name="admin_suggestions_api", prefix="admin_suggestions_api")
router = APIRouter(prefix="/admin/suggestions", tags=["admin-suggestions"])


@router.post("", response_model=APIResponse[SuggestionResponse])
async def create_suggestion(
    payload: SuggestionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("SUPER-ADMIN")),
):
    logger.info("REQUEST | create_suggestion | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        service = SuggestionService(SuggestionRepository(db))
        result = await service.create(payload)
        return success_response(data=result, message="Suggestion created successfully")
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_suggestion | %s", e.errors())
        return error_response(message="Invalid suggestion payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | create_suggestion | user_id=%s", current_user.user_id)
        return error_response(message="Failed to create suggestion", status_code=500)


@router.get("", response_model=APIResponse[SuggestionListResponse])
async def list_suggestions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    search: str | None = None,
    suggestion_type: str | None = None,
    is_active: bool | None = True,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("SUPER-ADMIN")),
):
    logger.info(
        "REQUEST | list_suggestions | user_id=%s | skip=%s | limit=%s | type=%s | active=%s",
        current_user.user_id,
        skip,
        limit,
        suggestion_type,
        is_active,
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SuggestionService(SuggestionRepository(db))
        result = await service.list(
            skip=skip,
            limit=limit,
            search=search,
            suggestion_type=suggestion_type,
            is_active=is_active,
        )
        return success_response(data=result, message="Suggestions fetched successfully")
    except Exception:
        logger.exception("ERROR | list_suggestions | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch suggestions", status_code=500)


@router.get("/{suggestion_id}", response_model=APIResponse[SuggestionResponse])
async def get_suggestion(
    suggestion_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("SUPER-ADMIN")),
):
    logger.info(
        "REQUEST | get_suggestion | user_id=%s | suggestion_id=%s",
        current_user.user_id,
        str(suggestion_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SuggestionService(SuggestionRepository(db))
        result = await service.get(suggestion_id)
        return success_response(data=result, message="Suggestion fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_suggestion | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_suggestion | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch suggestion", status_code=500)


@router.put("/{suggestion_id}", response_model=APIResponse[SuggestionResponse])
async def update_suggestion(
    suggestion_id: UUID,
    payload: SuggestionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("SUPER-ADMIN")),
):
    logger.info(
        "REQUEST | update_suggestion | user_id=%s | suggestion_id=%s",
        current_user.user_id,
        str(suggestion_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SuggestionService(SuggestionRepository(db))
        result = await service.update(suggestion_id, payload)
        return success_response(data=result, message="Suggestion updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_suggestion | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_suggestion | %s", e.errors())
        return error_response(message="Invalid suggestion payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | update_suggestion | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update suggestion", status_code=500)


@router.delete("/{suggestion_id}", response_model=APIResponse[SuggestionResponse])
async def delete_suggestion(
    suggestion_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("SUPER-ADMIN")),
):
    logger.info(
        "REQUEST | delete_suggestion | user_id=%s | suggestion_id=%s",
        current_user.user_id,
        str(suggestion_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SuggestionService(SuggestionRepository(db))
        result = await service.delete(suggestion_id)
        return success_response(data=result, message="Suggestion deleted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_suggestion | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_suggestion | user_id=%s", current_user.user_id)
        return error_response(message="Failed to delete suggestion", status_code=500)
