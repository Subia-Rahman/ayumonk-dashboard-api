from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.models.policy import Policy


class PolicyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, policy: Policy) -> Policy:
        self.db.add(policy)
        await self.db.commit()
        await self.db.refresh(policy)
        return policy

    async def get_by_id(self, policy_id: int) -> Policy | None:
        res = await self.db.execute(select(Policy).where(Policy.id == policy_id))
        return res.scalars().first()

    async def get_by_name(self, name: str, tenant_id: UUID) -> Policy | None:
        res = await self.db.execute(
            select(Policy).where(Policy.name == name, Policy.tenant_id == tenant_id)
        )
        return res.scalars().first()

    async def list(self, tenant_id: UUID, module: str | None = None):
        stmt = select(Policy).where(Policy.tenant_id == tenant_id, Policy.is_active.is_(True))
        if module:
            stmt = stmt.where(Policy.module == module)
        res = await self.db.execute(stmt)
        return res.scalars().all()

    async def list_by_ids(self, policy_ids: list[int]):
        if not policy_ids:
            return []
        res = await self.db.execute(
            select(Policy).where(Policy.id.in_(policy_ids))
        )
        return res.scalars().all()
