from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.schemas.auth import TokenUser
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.repositories.company_users import UserRepository
from config_service.app.repositories.push_subscription import (
    PushSubscriptionRepository,
)
from config_service.app.schemas.push import (
    PushSubscriptionPayload,
    PushUnsubscribePayload,
)
from config_service.app.services.push import PushSubscriptionService


logger = get_file_logger(name="push_api", prefix="push_api")
router = APIRouter(prefix="/api/push", tags=["push"])


def _make_service(db: AsyncSession) -> PushSubscriptionService:
    return PushSubscriptionService(PushSubscriptionRepository(db))


async def _resolve_company_user_id(current_user: TokenUser, db: AsyncSession):
    email = getattr(current_user, "email", None)
    if not email:
        raise BusinessException(message="User email missing on token", status_code=400)
    user = await UserRepository(db).get_by_email(email)
    if not user:
        raise BusinessException(
            message="Linked company user record not found",
            status_code=404,
        )
    return user.id


@router.post("/subscribe", response_model=APIResponse[dict])
async def subscribe(
    payload: PushSubscriptionPayload,
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info(
        "REQUEST | subscribe | user_id=%s | endpoint=%s",
        current_user.user_id, payload.endpoint,
    )
    try:
        user_id = await _resolve_company_user_id(current_user, db)
        entity = await _make_service(db).subscribe(payload, user_id=user_id)
        return success_response(
            data={"id": str(entity.id), "endpoint": entity.endpoint},
            message="Subscription saved",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | subscribe | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | subscribe | endpoint=%s", payload.endpoint)
        return error_response(message="Failed to save subscription", status_code=500)


@router.post("/unsubscribe", response_model=APIResponse[dict])
async def unsubscribe(
    payload: PushUnsubscribePayload,
    db: AsyncSession = Depends(get_db),
):
    logger.info("REQUEST | unsubscribe | endpoint=%s", payload.endpoint)
    try:
        removed = await _make_service(db).unsubscribe(payload.endpoint)
        return success_response(
            data={"removed": removed, "endpoint": payload.endpoint},
            message="Subscription removed" if removed else "Subscription not found",
        )
    except Exception:
        logger.exception("ERROR | unsubscribe | endpoint=%s", payload.endpoint)
        return error_response(message="Failed to remove subscription", status_code=500)
