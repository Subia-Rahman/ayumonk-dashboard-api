from uuid import UUID

from fastapi import APIRouter, Depends
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
from config_service.app.repositories.reminder_settings import (
    ReminderSettingsRepository,
)
from config_service.app.schemas.reminder_settings import (
    ReminderSettingsCreateRequest,
    ReminderSettingsResponse,
    ReminderSettingsSnoozeRequest,
    ReminderSettingsToggleRequest,
    ReminderSettingsUpdateRequest,
)
from config_service.app.services.reminder_settings import ReminderSettingsService


logger = get_file_logger(name="reminder_settings_api", prefix="reminder_settings_api")
router = APIRouter(prefix="/reminder-settings", tags=["reminder-settings"])


async def _resolve_user_id(current_user: TokenUser, db: AsyncSession) -> UUID:
    """Map the legacy auth user (int) to a CompanyUser UUID via email."""
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


def _make_service(db: AsyncSession) -> ReminderSettingsService:
    return ReminderSettingsService(ReminderSettingsRepository(db))


@router.get("", response_model=APIResponse[ReminderSettingsResponse])
async def get_reminder_settings(
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info("REQUEST | get_reminder_settings | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).get_or_default(user_id)
        return success_response(data=result, message="Reminder settings fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_reminder_settings | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_reminder_settings | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch reminder settings", status_code=500)


@router.post("", response_model=APIResponse[ReminderSettingsResponse])
async def create_reminder_settings(
    payload: ReminderSettingsCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info("REQUEST | create_reminder_settings | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).create(user_id, payload)
        return success_response(data=result, message="Reminder settings created successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | create_reminder_settings | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_reminder_settings | %s", e.errors())
        return error_response(message="Invalid reminder settings payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | create_reminder_settings | user_id=%s", current_user.user_id)
        return error_response(message="Failed to create reminder settings", status_code=500)


@router.put("", response_model=APIResponse[ReminderSettingsResponse])
async def update_reminder_settings(
    payload: ReminderSettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info("REQUEST | update_reminder_settings | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).update(user_id, payload)
        return success_response(data=result, message="Reminder settings updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_reminder_settings | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_reminder_settings | %s", e.errors())
        return error_response(message="Invalid reminder settings payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | update_reminder_settings | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update reminder settings", status_code=500)


@router.patch("/toggle", response_model=APIResponse[ReminderSettingsResponse])
async def toggle_reminder_field(
    payload: ReminderSettingsToggleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info(
        "REQUEST | toggle_reminder_field | user_id=%s | field=%s",
        current_user.user_id,
        payload.field,
    )
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).toggle(user_id, payload)
        return success_response(data=result, message="Reminder field toggled successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | toggle_reminder_field | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | toggle_reminder_field | %s", e.errors())
        return error_response(message="Invalid toggle payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | toggle_reminder_field | user_id=%s", current_user.user_id)
        return error_response(message="Failed to toggle reminder field", status_code=500)


@router.post("/snooze", response_model=APIResponse[ReminderSettingsResponse])
async def snooze_reminders(
    payload: ReminderSettingsSnoozeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info(
        "REQUEST | snooze_reminders | user_id=%s | duration=%s",
        current_user.user_id,
        payload.duration,
    )
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).snooze(user_id, payload)
        return success_response(data=result, message="Reminders snoozed successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | snooze_reminders | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | snooze_reminders | %s", e.errors())
        return error_response(message="Invalid snooze payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | snooze_reminders | user_id=%s", current_user.user_id)
        return error_response(message="Failed to snooze reminders", status_code=500)


@router.delete("/snooze", response_model=APIResponse[ReminderSettingsResponse])
async def clear_snooze(
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
):
    logger.info("REQUEST | clear_snooze | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        user_id = await _resolve_user_id(current_user, db)
        result = await _make_service(db).clear_snooze(user_id)
        return success_response(data=result, message="Snooze cleared successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | clear_snooze | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | clear_snooze | user_id=%s", current_user.user_id)
        return error_response(message="Failed to clear snooze", status_code=500)
