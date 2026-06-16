from __future__ import annotations
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.schemas.auth import TokenUser
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.repositories.company_users import UserRepository
from config_service.app.repositories.notification import NotificationRepository
from config_service.app.schemas.notification import (
    BulkActionResponse,
    NotificationActionRequest,
    NotificationListResponse,
    NotificationResponse,
    NotificationSnoozeRequest,
    UnreadCountResponse,
)
from config_service.app.services.notification import NotificationService


logger = get_file_logger(name="notifications_api", prefix="notifications_api")
router = APIRouter(prefix="/notifications", tags=["notifications"])


async def _resolve_user_id(current_user: TokenUser, db: AsyncSession) -> UUID:
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


def _make_service(db: AsyncSession) -> NotificationService:
    return NotificationService(NotificationRepository(db))


@router.get("", response_model=APIResponse[NotificationListResponse])
async def list_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    is_read: Optional[bool] = Query(default=None),
    type: Optional[str] = Query(default=None),
    include_dismissed: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info(
        "REQUEST | list_notifications | user_id=%s | skip=%s | limit=%s",
        current_user.user_id, skip, limit,
    )
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).list(
            user_id=user_id,
            skip=skip,
            limit=limit,
            is_read=is_read,
            type_=type,
            include_dismissed=include_dismissed,
        )
        return success_response(data=result, message="Notifications fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | list_notifications | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | list_notifications | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch notifications", status_code=500)


@router.get("/unread-count", response_model=APIResponse[UnreadCountResponse])
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    db.info["user_id"] = current_user.user_id
    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).unread_count(user_id)
        return success_response(data=result, message="Unread count fetched successfully")
    except BusinessException as e:
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_unread_count | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch unread count", status_code=500)


@router.patch("/{notification_id}/read", response_model=APIResponse[NotificationResponse])
async def mark_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info(
        "REQUEST | mark_read | user_id=%s | notification_id=%s",
        current_user.user_id, str(notification_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).mark_read(notification_id, user_id)
        return success_response(data=result, message="Notification marked as read")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | mark_read | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | mark_read | user_id=%s", current_user.user_id)
        return error_response(message="Failed to mark notification as read", status_code=500)


@router.patch("/{notification_id}/dismiss", response_model=APIResponse[NotificationResponse])
async def dismiss_notification(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info(
        "REQUEST | dismiss_notification | user_id=%s | notification_id=%s",
        current_user.user_id, str(notification_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).dismiss(notification_id, user_id)
        return success_response(data=result, message="Notification dismissed")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | dismiss_notification | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | dismiss_notification | user_id=%s", current_user.user_id)
        return error_response(message="Failed to dismiss notification", status_code=500)


@router.patch("/{notification_id}/snooze", response_model=APIResponse[NotificationResponse])
async def snooze_notification(
    notification_id: UUID,
    payload: NotificationSnoozeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info(
        "REQUEST | snooze_notification | user_id=%s | notification_id=%s | duration=%s",
        current_user.user_id, str(notification_id), payload.duration,
    )
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).snooze(notification_id, user_id, payload)
        return success_response(data=result, message="Notification snoozed")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | snooze_notification | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        return error_response(message="Invalid snooze payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | snooze_notification | user_id=%s", current_user.user_id)
        return error_response(message="Failed to snooze notification", status_code=500)


@router.patch("/{notification_id}/action", response_model=APIResponse[NotificationResponse])
async def record_action(
    notification_id: UUID,
    payload: NotificationActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info(
        "REQUEST | record_action | user_id=%s | notification_id=%s | action=%s",
        current_user.user_id, str(notification_id), payload.action,
    )
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).record_action(notification_id, user_id, payload)
        return success_response(data=result, message="Action recorded")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | record_action | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        return error_response(message="Invalid action payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | record_action | user_id=%s", current_user.user_id)
        return error_response(message="Failed to record action", status_code=500)


@router.post("/mark-all-read", response_model=APIResponse[BulkActionResponse])
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info("REQUEST | mark_all_read | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).mark_all_read(user_id)
        return success_response(data=result, message="All notifications marked as read")
    except BusinessException as e:
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | mark_all_read | user_id=%s", current_user.user_id)
        return error_response(message="Failed to mark all notifications as read", status_code=500)


@router.delete("", response_model=APIResponse[BulkActionResponse])
async def clear_all(
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info("REQUEST | clear_all_notifications | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).clear_all(user_id)
        return success_response(data=result, message="All notifications cleared")
    except BusinessException as e:
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | clear_all_notifications | user_id=%s", current_user.user_id)
        return error_response(message="Failed to clear notifications", status_code=500)
