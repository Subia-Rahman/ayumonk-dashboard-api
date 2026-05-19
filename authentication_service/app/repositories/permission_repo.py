from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.models.permission import Permission


class PermissionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, perm: Permission) -> Permission:
        self.db.add(perm)
        await self.db.commit()
        await self.db.refresh(perm)
        return perm

    async def get_by_id(self, permission_id: int) -> Permission | None:
        res = await self.db.execute(
            select(Permission).where(Permission.id == permission_id)
        )
        return res.scalars().first()

    async def get_by_codename(self, codename: str) -> Permission | None:
        res = await self.db.execute(
            select(Permission).where(Permission.codename == codename)
        )
        return res.scalars().first()

    async def get_by_name(self, name: str) -> Permission | None:
        res = await self.db.execute(
            select(Permission).where(Permission.name == name)
        )
        return res.scalars().first()

    async def list(self):
        res = await self.db.execute(select(Permission))
        return res.scalars().all()

    async def list_by_codenames(self, codenames: list[str]):
        if not codenames:
            return []
        res = await self.db.execute(
            select(Permission).where(Permission.codename.in_(codenames))
        )
        return res.scalars().all()

    async def update(self, perm: Permission) -> Permission:
        self.db.add(perm)
        await self.db.commit()
        await self.db.refresh(perm)
        return perm

    async def delete(self, perm: Permission) -> None:
        await self.db.delete(perm)
        await self.db.commit()
