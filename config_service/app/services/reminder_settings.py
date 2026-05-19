from datetime import datetime, time, timedelta, timezone
from typing import Optional
from uuid import UUID

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.reminder_settings import ReminderSettings
from config_service.app.repositories.reminder_settings import (
    ReminderSettingsRepository,
)
from config_service.app.schemas.reminder_settings import (
    REMINDER_TOGGLE_FIELDS,
    ReminderSettingsCreateRequest,
    ReminderSettingsResponse,
    ReminderSettingsSnoozeRequest,
    ReminderSettingsToggleRequest,
    ReminderSettingsUpdateRequest,
)


SNOOZE_DURATIONS = {
    "24h": timedelta(hours=24),
    "48h": timedelta(hours=48),
    "7d": timedelta(days=7),
}


DEFAULT_REMINDER_TIME = time(20, 0)
DEFAULT_TIMEZONE = "UTC"


class ReminderSettingsService:
    def __init__(self, repo: ReminderSettingsRepository):
        self.repo = repo

    async def get_or_default(self, user_id: UUID) -> ReminderSettingsResponse:
        existing = await self.repo.get_by_user_id(user_id)
        if existing:
            return ReminderSettingsResponse.model_validate(existing)
        return self._default_payload(user_id)

    async def create(
        self,
        user_id: UUID,
        payload: ReminderSettingsCreateRequest,
    ) -> ReminderSettingsResponse:
        existing = await self.repo.get_by_user_id(user_id)
        if existing:
            raise BusinessException(
                message="Reminder settings already exist for this user",
                status_code=409,
            )

        entity = ReminderSettings(
            user_id=user_id,
            **payload.model_dump(),
        )
        entity = await self.repo.create(entity)
        return ReminderSettingsResponse.model_validate(entity)

    async def update(
        self,
        user_id: UUID,
        payload: ReminderSettingsUpdateRequest,
    ) -> ReminderSettingsResponse:
        entity = await self.repo.get_by_user_id(user_id)
        if not entity:
            entity = await self._create_with_defaults(user_id)

        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(entity, field, value)

        entity = await self.repo.update(entity)
        return ReminderSettingsResponse.model_validate(entity)

    async def toggle(
        self,
        user_id: UUID,
        payload: ReminderSettingsToggleRequest,
    ) -> ReminderSettingsResponse:
        if payload.field not in REMINDER_TOGGLE_FIELDS:
            raise BusinessException(
                message=f"Field '{payload.field}' is not toggleable",
                status_code=400,
            )

        entity = await self.repo.get_by_user_id(user_id)
        if not entity:
            entity = await self._create_with_defaults(user_id)

        current = bool(getattr(entity, payload.field))
        new_value = payload.value if payload.value is not None else not current
        setattr(entity, payload.field, new_value)

        entity = await self.repo.update(entity)
        return ReminderSettingsResponse.model_validate(entity)

    async def snooze(
        self,
        user_id: UUID,
        payload: ReminderSettingsSnoozeRequest,
    ) -> ReminderSettingsResponse:
        delta = SNOOZE_DURATIONS.get(payload.duration)
        if delta is None:
            raise BusinessException(
                message="Invalid snooze duration",
                status_code=400,
            )

        entity = await self.repo.get_by_user_id(user_id)
        if not entity:
            entity = await self._create_with_defaults(user_id)

        entity.snooze_until = datetime.now(timezone.utc).replace(tzinfo=None) + delta
        entity = await self.repo.update(entity)
        return ReminderSettingsResponse.model_validate(entity)

    async def clear_snooze(self, user_id: UUID) -> ReminderSettingsResponse:
        entity = await self.repo.get_by_user_id(user_id)
        if not entity:
            entity = await self._create_with_defaults(user_id)
        entity.snooze_until = None
        entity = await self.repo.update(entity)
        return ReminderSettingsResponse.model_validate(entity)

    async def _create_with_defaults(self, user_id: UUID) -> ReminderSettings:
        entity = ReminderSettings(
            user_id=user_id,
            is_enabled=True,
            email_enabled=True,
            push_enabled=False,
            whatsapp_enabled=False,
            reminder_time=DEFAULT_REMINDER_TIME,
            timezone=DEFAULT_TIMEZONE,
            daily_challenge=True,
            streak_alert=True,
            program_ending=True,
            new_program=True,
            badge_milestone=True,
        )
        return await self.repo.create(entity)

    @staticmethod
    def _default_payload(user_id: UUID) -> ReminderSettingsResponse:
        now = datetime.utcnow()
        from uuid import uuid4

        return ReminderSettingsResponse(
            id=uuid4(),
            user_id=user_id,
            is_enabled=True,
            email_enabled=True,
            push_enabled=False,
            whatsapp_enabled=False,
            reminder_time=DEFAULT_REMINDER_TIME,
            timezone=DEFAULT_TIMEZONE,
            daily_challenge=True,
            streak_alert=True,
            program_ending=True,
            new_program=True,
            badge_milestone=True,
            snooze_until=None,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def is_reminder_suppressed(entity: ReminderSettings, now_utc: Optional[datetime] = None) -> bool:
        """True when reminders should NOT be delivered (disabled or snoozed)."""
        if not entity.is_enabled:
            return True
        if entity.snooze_until is None:
            return False
        now_utc = now_utc or datetime.now(timezone.utc).replace(tzinfo=None)
        return entity.snooze_until > now_utc
