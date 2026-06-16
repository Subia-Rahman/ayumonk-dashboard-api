from __future__ import annotations
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.models.role import Role


class RoleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, role: Role) -> Role:
        self.db.add(role)
        await self.db.commit()
        await self.db.refresh(role)
        return role

    async def get_by_id(self, role_id: int) -> Role | None:
        res = await self.db.execute(select(Role).where(Role.id == role_id))
        return res.scalars().first()

    async def get_by_name(self, name: str, tenant_id: UUID) -> Role | None:
        res = await self.db.execute(
            select(Role).where(Role.name == name, Role.tenant_id == tenant_id)
        )
        return res.scalars().first()

    async def list(self, tenant_id: UUID):
        res = await self.db.execute(
            select(Role).where(Role.tenant_id == tenant_id)
        )
        return res.scalars().all()

    async def update(self, role: Role) -> Role:
        self.db.add(role)
        await self.db.commit()
        await self.db.refresh(role)
        return role

    async def delete(self, role: Role) -> None:
        await self.db.delete(role)
        await self.db.commit()
