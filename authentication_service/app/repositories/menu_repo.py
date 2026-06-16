from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.models.menu import Menu


class MenuRepository:
    """Menus are a global platform-wide catalog (tenant_id IS NULL).
    Tenant-specific access is granted via role_menus, not by per-tenant
    menu rows."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, menu: Menu) -> Menu:
        self.db.add(menu)
        await self.db.commit()
        await self.db.refresh(menu)
        return menu

    async def list(self):
        """Return active menus."""
        res = await self.db.execute(select(Menu).where(Menu.is_active.is_(True)))
        return res.scalars().all()

    async def list_all(self):
        """Return every menu (active + inactive). Used by admin listings."""
        res = await self.db.execute(select(Menu))
        return res.scalars().all()

    async def get_by_id(self, menu_id: int) -> Menu | None:
        res = await self.db.execute(select(Menu).where(Menu.id == menu_id))
        return res.scalars().first()

    async def get_by_slug(self, slug: str) -> Menu | None:
        res = await self.db.execute(select(Menu).where(Menu.slug == slug))
        return res.scalars().first()

    async def update(self, menu: Menu) -> Menu:
        self.db.add(menu)
        await self.db.commit()
        await self.db.refresh(menu)
        return menu

    async def delete(self, menu: Menu) -> None:
        await self.db.delete(menu)
        await self.db.commit()
