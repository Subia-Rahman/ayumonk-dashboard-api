from __future__ import annotations
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.kpi_suggestion_mapping import KPISuggestionMapping


class KPISuggestionMappingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, obj: KPISuggestionMapping) -> KPISuggestionMapping:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: KPISuggestionMapping) -> KPISuggestionMapping:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, mapping_id):
        stmt = select(KPISuggestionMapping).where(
            KPISuggestionMapping.id == mapping_id,
            KPISuggestionMapping.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        kpi_key=None,
        suggestion_id=None,
        trigger_mode: str | None = None,
        is_active: bool | None = True,
    ):
        stmt = select(KPISuggestionMapping).where(KPISuggestionMapping.is_deleted == False)
        if is_active is not None:
            stmt = stmt.where(KPISuggestionMapping.is_active == is_active)
        if kpi_key:
            stmt = stmt.where(KPISuggestionMapping.kpi_key == kpi_key)
        if suggestion_id:
            stmt = stmt.where(KPISuggestionMapping.suggestion_id == suggestion_id)
        if trigger_mode:
            stmt = stmt.where(func.lower(KPISuggestionMapping.trigger_mode) == trigger_mode.lower())

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(KPISuggestionMapping.priority.asc()).offset(skip).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total
