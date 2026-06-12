"""User-facing suggestion endpoints (Phase 4).

  * GET  /api/v1/suggestions/my            — read engine output
  * POST /api/v1/suggestions/{log_id}/action — record done/skipped/saved

Both endpoints are user-scoped: the JWT subject's email is the lookup /
write key. Authorisation for the action endpoint is enforced inside the
service (the log row must belong to the caller).
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import get_current_user
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.schemas.user_suggestions import (
    SuggestionActionRequest,
    SuggestionActionResponse,
    UserSuggestionItem,
    UserSuggestionsResponse,
)
from config_service.app.services.user_suggestions import UserSuggestionsService


logger = get_file_logger(name="user_suggestions_api", prefix="user_suggestions_api")
router = APIRouter(prefix="/suggestions", tags=["suggestions-user"])


@router.get("/my", response_model=APIResponse[UserSuggestionsResponse])
async def get_my_suggestions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Returns the suggestion-engine picks for the caller's most recent
    submission. Spec §8.2: drives the Lifestyle Suggestions Panel on the
    Wellness page (cards grouped by suggestion_type, dosha-personalised,
    up to 2 Aahar + 2 Vihar + 2 Aushadh).

    404 when the user has never had a submission produce engine output
    (e.g. all KPIs are in the 'good' band — no recommendations needed)."""
    logger.info(
        "REQUEST | get_my_suggestions | user_id=%s | email=%s",
        current_user.user_id,
        current_user.email,
    )
    db.info["user_id"] = current_user.user_id

    try:
        result = await UserSuggestionsService(db).get_my_latest(
            current_user.email
        )
        return success_response(
            data=UserSuggestionsResponse(
                response_id=result["response_id"],
                submitted_at=result["submitted_at"],
                items=[UserSuggestionItem(**item) for item in result["items"]],
            ),
            message="Suggestions fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_my_suggestions | %s", e.message)
        return error_response(
            message=e.message, status_code=e.status_code, errors=e.errors
        )
    except Exception:
        logger.exception(
            "ERROR | get_my_suggestions | user_id=%s", current_user.user_id
        )
        return error_response(
            message="Failed to fetch suggestions", status_code=500
        )


@router.post(
    "/{log_id}/action",
    response_model=APIResponse[SuggestionActionResponse],
)
async def record_suggestion_action(
    log_id: UUID,
    payload: SuggestionActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Record what the user did with a suggestion: Done / Skipped /
    Saved. Service-side check ensures the log row belongs to the
    caller — 404 leak on other users' rows is intentional (don't
    confirm existence)."""
    logger.info(
        "REQUEST | record_suggestion_action | user_id=%s | log_id=%s | action=%s",
        current_user.user_id,
        str(log_id),
        payload.action,
    )
    db.info["user_id"] = current_user.user_id

    try:
        row = await UserSuggestionsService(db).record_action(
            log_id=log_id,
            email=current_user.email,
            action=payload.action,
            actor_user_id=current_user.user_id,
        )
        return success_response(
            data=SuggestionActionResponse(
                log_id=row.id,
                action=row.action,
                actioned_at=row.actioned_at,
            ),
            message="Suggestion action recorded",
        )
    except BusinessException as e:
        logger.warning(
            "BUSINESS_ERROR | record_suggestion_action | %s", e.message
        )
        return error_response(
            message=e.message, status_code=e.status_code, errors=e.errors
        )
    except ValidationError as e:
        logger.warning(
            "VALIDATION_ERROR | record_suggestion_action | %s", e.errors()
        )
        return error_response(
            message="Invalid action payload", status_code=422, errors=e.errors()
        )
    except Exception:
        logger.exception(
            "ERROR | record_suggestion_action | user_id=%s",
            current_user.user_id,
        )
        return error_response(
            message="Failed to record suggestion action", status_code=500
        )
