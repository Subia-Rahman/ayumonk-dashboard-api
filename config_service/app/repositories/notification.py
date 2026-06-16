from __future__ import annotations
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.notification import Notification


class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, obj: Notification) -> Notification:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: Notification) -> Notification:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, notification_id: UUID, user_id: UUID) -> Optional[Notification]:
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
            Notification.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        skip: int,
        limit: int,
        is_read: Optional[bool] = None,
        type_: Optional[str] = None,
        include_dismissed: bool = False,
    ) -> tuple[list[Notification], int]:
        stmt = select(Notification).where(
            Notification.user_id == user_id,
            Notification.is_deleted == False,
        )
        if not include_dismissed:
            stmt = stmt.where(Notification.dismissed_at.is_(None))
        if is_read is not None:
            stmt = stmt.where(Notification.is_read == is_read)
        if type_ is not None:
            stmt = stmt.where(Notification.type == type_)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Notification.created_at.desc()).offset(skip).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total

    async def unread_count(self, user_id: UUID) -> int:
        stmt = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_deleted == False,
            Notification.is_read == False,
            Notification.dismissed_at.is_(None),
        )
        res = await self.db.execute(stmt)
        return int(res.scalar_one())

    async def mark_all_read(self, user_id: UUID, now: datetime) -> int:
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_deleted == False,
                Notification.is_read == False,
            )
            .values(is_read=True, read_at=now, updated_at=now)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return int(result.rowcount or 0)

    async def clear_all(self, user_id: UUID, now: datetime) -> int:
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_deleted == False,
            )
            .values(is_deleted=True, is_active=False, updated_at=now)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return int(result.rowcount or 0)
