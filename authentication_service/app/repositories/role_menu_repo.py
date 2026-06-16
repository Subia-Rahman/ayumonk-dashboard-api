from __future__ import annotations
from uuid import UUID

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.models.role_menu import RoleMenu


class RoleMenuRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def replace(self, role_id: int, menu_ids: list[int], tenant_id: UUID):
        await self.db.execute(
            delete(RoleMenu).where(
                RoleMenu.role_id == role_id,
                RoleMenu.tenant_id == tenant_id,
            )
        )
        for mid in menu_ids:
            self.db.add(RoleMenu(role_id=role_id, menu_id=mid, tenant_id=tenant_id))
        await self.db.commit()

    async def list_by_role(self, role_id: int, tenant_id: UUID):
        res = await self.db.execute(
            select(RoleMenu).where(
                RoleMenu.role_id == role_id,
                RoleMenu.tenant_id == tenant_id,
            )
        )
        return res.scalars().all()

    async def add_many(
        self,
        role_id: int,
        menu_ids: list[int],
        tenant_id: UUID,
        access_level: str = "view",
    ):
        existing = {
            (rm.role_id, rm.menu_id): rm
            for rm in await self.list_by_role(role_id, tenant_id)
        }
        for mid in menu_ids:
            row = existing.get((role_id, mid))
            if row:
                row.access_level = access_level
                self.db.add(row)
            else:
                self.db.add(
                    RoleMenu(
                        role_id=role_id,
                        menu_id=mid,
                        tenant_id=tenant_id,
                        access_level=access_level,
                    )
                )
        await self.db.commit()

    async def upsert_items(
        self,
        role_id: int,
        items: list[tuple[int, str]],
        tenant_id: UUID,
    ):
        existing = {
            (rm.role_id, rm.menu_id): rm
            for rm in await self.list_by_role(role_id, tenant_id)
        }
        for menu_id, access_level in items:
            row = existing.get((role_id, menu_id))
            if row:
                row.access_level = access_level
                self.db.add(row)
            else:
                self.db.add(
                    RoleMenu(
                        role_id=role_id,
                        menu_id=menu_id,
                        tenant_id=tenant_id,
                        access_level=access_level,
                    )
                )
        await self.db.commit()

    async def remove_many(self, role_id: int, menu_ids: list[int], tenant_id: UUID):
        await self.db.execute(
            delete(RoleMenu).where(
                RoleMenu.role_id == role_id,
                RoleMenu.tenant_id == tenant_id,
                RoleMenu.menu_id.in_(menu_ids),
            )
        )
        await self.db.commit()

    async def count_by_menu(self, menu_id: int) -> int:
        res = await self.db.execute(
            select(func.count(RoleMenu.role_id)).where(RoleMenu.menu_id == menu_id)
        )
        return int(res.scalar() or 0)
