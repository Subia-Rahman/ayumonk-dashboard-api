from __future__ import annotations
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.push_subscription import PushSubscription


class PushSubscriptionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_endpoint(self, endpoint: str) -> Optional[PushSubscription]:
        stmt = select(PushSubscription).where(
            PushSubscription.endpoint == endpoint,
            PushSubscription.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_by_user_id(self, user_id) -> list[PushSubscription]:
        stmt = select(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def upsert(
        self,
        *,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_id=None,
    ) -> PushSubscription:
        existing = await self.get_by_endpoint(endpoint)
        if existing:
            existing.p256dh = p256dh
            existing.auth = auth
            if user_id is not None:
                existing.user_id = user_id
            self.db.add(existing)
            await self.db.commit()
            await self.db.refresh(existing)
            return existing

        obj = PushSubscription(
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_id=user_id,
        )
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def delete_by_endpoint(self, endpoint: str) -> bool:
        existing = await self.get_by_endpoint(endpoint)
        if not existing:
            return False
        await self.db.delete(existing)
        await self.db.commit()
        return True
