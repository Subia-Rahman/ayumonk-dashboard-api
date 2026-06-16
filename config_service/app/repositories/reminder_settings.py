from __future__ import annotations
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.reminder_settings import ReminderSettings


class ReminderSettingsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, obj: ReminderSettings) -> ReminderSettings:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: ReminderSettings) -> ReminderSettings:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def get_by_user_id(self, user_id: UUID) -> Optional[ReminderSettings]:
        stmt = select(ReminderSettings).where(
            ReminderSettings.user_id == user_id,
            ReminderSettings.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_active_due(self) -> list[ReminderSettings]:
        """Return all enabled reminder rows. The scheduler filters by time/tz."""
        stmt = select(ReminderSettings).where(
            ReminderSettings.is_deleted == False,
            ReminderSettings.is_active == True,
            ReminderSettings.is_enabled == True,
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())
