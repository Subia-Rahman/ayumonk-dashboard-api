from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from authentication_service.app.models.tenant import Tenant


class TenantRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, tenant: Tenant) -> Tenant:
        self.db.add(tenant)
        await self.db.commit()
        await self.db.refresh(tenant)
        return tenant

    async def get_by_id(self, tenant_id: int) -> Tenant | None:
        res = await self.db.execute(select(Tenant).where(Tenant.id == tenant_id))
        return res.scalars().first()

    async def get_by_code(self, code: str) -> Tenant | None:
        res = await self.db.execute(select(Tenant).where(Tenant.code == code))
        return res.scalars().first()

    async def list(self, skip: int = 0, limit: int = 100):
        res = await self.db.execute(
            select(Tenant).offset(skip).limit(limit).order_by(Tenant.id.desc())
        )
        return res.scalars().all()

    async def update(self, tenant: Tenant) -> Tenant:
        self.db.add(tenant)
        await self.db.commit()
        await self.db.refresh(tenant)
        return tenant

    async def delete(self, tenant: Tenant):
        await self.db.delete(tenant)
        await self.db.commit()
