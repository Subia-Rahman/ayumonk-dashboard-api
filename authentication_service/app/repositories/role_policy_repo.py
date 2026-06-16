from __future__ import annotations
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.models.role_policy import RolePolicy


class RolePolicyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_role(self, role_id: int, tenant_id: UUID):
        res = await self.db.execute(
            select(RolePolicy).where(
                RolePolicy.role_id == role_id,
                RolePolicy.tenant_id == tenant_id,
            )
        )
        return res.scalars().all()

    async def add_many(self, role_id: int, policy_ids: list[int], tenant_id: UUID):
        existing = {
            rp.policy_id for rp in await self.list_by_role(role_id, tenant_id)
        }
        for pid in policy_ids:
            if pid in existing:
                continue
            self.db.add(RolePolicy(role_id=role_id, policy_id=pid, tenant_id=tenant_id))
        await self.db.commit()

    async def remove_many(self, role_id: int, policy_ids: list[int], tenant_id: UUID):
        await self.db.execute(
            delete(RolePolicy).where(
                RolePolicy.role_id == role_id,
                RolePolicy.tenant_id == tenant_id,
                RolePolicy.policy_id.in_(policy_ids),
            )
        )
        await self.db.commit()
