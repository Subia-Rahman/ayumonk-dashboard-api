from __future__ import annotations
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.models.user_policy import UserPolicy


class UserPolicyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_user(self, user_id: int, tenant_id: UUID):
        res = await self.db.execute(
            select(UserPolicy).where(
                UserPolicy.user_id == user_id,
                UserPolicy.tenant_id == tenant_id,
            )
        )
        return res.scalars().all()

    async def add_many(self, user_id: int, policy_ids: list[int], tenant_id: UUID):
        existing = {up.policy_id for up in await self.list_by_user(user_id, tenant_id)}
        for pid in policy_ids:
            if pid in existing:
                continue
            self.db.add(UserPolicy(user_id=user_id, policy_id=pid, tenant_id=tenant_id))
        await self.db.commit()

    async def remove_many(self, user_id: int, policy_ids: list[int], tenant_id: UUID):
        await self.db.execute(
            delete(UserPolicy).where(
                UserPolicy.user_id == user_id,
                UserPolicy.tenant_id == tenant_id,
                UserPolicy.policy_id.in_(policy_ids),
            )
        )
        await self.db.commit()
