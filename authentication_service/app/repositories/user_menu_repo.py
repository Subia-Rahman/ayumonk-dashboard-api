from __future__ import annotations
from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.models.user_menu import UserMenu


class UserMenuRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, menu: UserMenu) -> UserMenu:
        self.db.add(menu)
        await self.db.commit()
        await self.db.refresh(menu)
        return menu

    async def list_by_user(self, user_id: int, tenant_id: UUID):
        res = await self.db.execute(
            select(UserMenu).where(
                UserMenu.user_id == user_id,
                UserMenu.tenant_id == tenant_id,
            )
        )
        return res.scalars().all()

    async def upsert(
        self,
        user_id: int,
        menu_id: int,
        tenant_id: UUID,
        access_level: str = "view",
        is_active: bool = True,
    ) -> UserMenu:
        res = await self.db.execute(
            select(UserMenu).where(
                UserMenu.user_id == user_id,
                UserMenu.menu_id == menu_id,
                UserMenu.tenant_id == tenant_id,
            )
        )
        row = res.scalars().first()
        if row:
            row.access_level = access_level
            row.is_active = is_active
            self.db.add(row)
        else:
            row = UserMenu(
                user_id=user_id,
                menu_id=menu_id,
                tenant_id=tenant_id,
                access_level=access_level,
                is_active=is_active,
            )
            self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def upsert_items(
        self,
        user_id: int,
        items: list[tuple[int, str, bool]],
        tenant_id: UUID,
    ):
        for menu_id, access_level, is_active in items:
            await self.upsert(user_id, menu_id, tenant_id, access_level, is_active)

    async def delete_for_user(self, user_id: int, tenant_id: UUID):
        await self.db.execute(
            delete(UserMenu).where(
                UserMenu.user_id == user_id,
                UserMenu.tenant_id == tenant_id,
            )
        )
        await self.db.commit()
