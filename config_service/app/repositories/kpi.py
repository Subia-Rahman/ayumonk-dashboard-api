from __future__ import annotations
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from config_service.app.models.kpi import KPI


class KPIRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, obj: KPI) -> KPI:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: KPI) -> KPI:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, kpi_key, company_id=None):
        stmt = select(KPI).where(
            KPI.kpi_key == kpi_key,
            KPI.is_deleted == False,
        )
        if company_id is not None:
            stmt = stmt.where(KPI.company_id == company_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_name_and_theme(self, name: str, theme_id, company_id=None):
        stmt = select(KPI).where(
            KPI.display_name == name,
            KPI.theme_key == theme_id,
            KPI.is_deleted == False,
        )
        if company_id is not None:
            stmt = stmt.where(KPI.company_id == company_id)
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def get_by_name(self, name: str, company_id=None):
        stmt = select(KPI).where(
            func.lower(KPI.display_name) == func.lower(name),
            KPI.is_deleted == False,
        )
        if company_id is not None:
            stmt = stmt.where(KPI.company_id == company_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        company_id=None,
        theme_key=None,
        search: str | None = None,
        is_active: bool | None = True,
    ):
        stmt = select(KPI).where(KPI.is_deleted == False)
        if company_id is not None:
            stmt = stmt.where(KPI.company_id == company_id)
        if is_active is not None:
            stmt = stmt.where(KPI.is_active == is_active)
        if theme_key:
            stmt = stmt.where(KPI.theme_key == theme_key)
        if search:
            stmt = stmt.where(func.lower(KPI.display_name).like(f"%{search.lower()}%"))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(KPI.display_name.asc()).offset(skip).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total

    async def list_by_ids(self, kpi_keys: list, company_id=None):
        if not kpi_keys:
            return []
        stmt = select(KPI).where(
            KPI.kpi_key.in_(kpi_keys),
            KPI.is_deleted == False,
        )
        if company_id is not None:
            stmt = stmt.where(KPI.company_id == company_id)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

