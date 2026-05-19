from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from config_service.app.models.theme import Theme


class ThemeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, obj: Theme) -> Theme:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: Theme) -> Theme:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, theme_key, company_id=None):
        stmt = select(Theme).where(
            Theme.theme_key == theme_key,
            Theme.is_deleted == False,
        )
        if company_id is not None:
            stmt = stmt.where(Theme.company_id == company_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_name(self, name: str, company_id=None):
        stmt = select(Theme).where(
            Theme.theme_display_name == name,
            Theme.is_deleted == False,
        )
        if company_id is not None:
            stmt = stmt.where(Theme.company_id == company_id)
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def get_by_name_ci(self, name: str, company_id=None):
        stmt = select(Theme).where(
            func.lower(Theme.theme_display_name) == func.lower(name),
            Theme.is_deleted == False,
        )
        if company_id is not None:
            stmt = stmt.where(Theme.company_id == company_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        company_id=None,
        search: str | None = None,
        is_active: bool | None = True,
    ):
        stmt = select(Theme).where(Theme.is_deleted == False)
        if company_id is not None:
            stmt = stmt.where(Theme.company_id == company_id)
        if is_active is not None:
            stmt = stmt.where(Theme.is_active == is_active)
        if search:
            stmt = stmt.where(func.lower(Theme.theme_display_name).like(f"%{search.lower()}%"))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Theme.theme_display_name.asc()).offset(skip).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total
