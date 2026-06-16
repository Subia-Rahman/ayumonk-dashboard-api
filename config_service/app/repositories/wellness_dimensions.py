from __future__ import annotations
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.kpi import KPI
from config_service.app.models.wellness_dimensions import (
    WellnessDimension,
    WellnessDimensionKpiMapping,
)


class WellnessDimensionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(
        self, dimension_id: int, *, company_id: UUID
    ) -> Optional[WellnessDimension]:
        stmt = select(WellnessDimension).where(
            WellnessDimension.id == dimension_id,
            WellnessDimension.company_id == company_id,
            WellnessDimension.is_deleted == False,  # noqa: E712
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_key(
        self, dimension_key: str, *, company_id: UUID
    ) -> Optional[WellnessDimension]:
        stmt = select(WellnessDimension).where(
            func.lower(WellnessDimension.dimension_key) == dimension_key.lower(),
            WellnessDimension.company_id == company_id,
            WellnessDimension.is_deleted == False,  # noqa: E712
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_with_kpi_counts(
        self, *, company_id: UUID
    ) -> list[tuple[WellnessDimension, int]]:
        """Every non-deleted dimension for the company plus the count of its
        active KPI mappings, ordered by display_order then id."""
        count_subq = (
            select(
                WellnessDimensionKpiMapping.dimension_id,
                func.count(WellnessDimensionKpiMapping.id).label("kpi_count"),
            )
            .where(
                WellnessDimensionKpiMapping.company_id == company_id,
                WellnessDimensionKpiMapping.is_active == True,  # noqa: E712
                WellnessDimensionKpiMapping.is_deleted == False,  # noqa: E712
            )
            .group_by(WellnessDimensionKpiMapping.dimension_id)
            .subquery()
        )

        stmt = (
            select(WellnessDimension, func.coalesce(count_subq.c.kpi_count, 0))
            .outerjoin(
                count_subq,
                count_subq.c.dimension_id == WellnessDimension.id,
            )
            .where(
                WellnessDimension.company_id == company_id,
                WellnessDimension.is_deleted == False,  # noqa: E712
            )
            .order_by(
                WellnessDimension.display_order.asc(),
                WellnessDimension.id.asc(),
            )
        )
        res = await self.db.execute(stmt)
        return [(row[0], int(row[1])) for row in res.all()]

    async def active_mapping_count(
        self, dimension_id: int, *, company_id: UUID
    ) -> int:
        stmt = select(func.count(WellnessDimensionKpiMapping.id)).where(
            WellnessDimensionKpiMapping.dimension_id == dimension_id,
            WellnessDimensionKpiMapping.company_id == company_id,
            WellnessDimensionKpiMapping.is_active == True,  # noqa: E712
            WellnessDimensionKpiMapping.is_deleted == False,  # noqa: E712
        )
        return int((await self.db.execute(stmt)).scalar_one())


class WellnessDimensionKpiMappingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(
        self, mapping_id: int, *, company_id: UUID
    ) -> Optional[WellnessDimensionKpiMapping]:
        stmt = select(WellnessDimensionKpiMapping).where(
            WellnessDimensionKpiMapping.id == mapping_id,
            WellnessDimensionKpiMapping.company_id == company_id,
            WellnessDimensionKpiMapping.is_deleted == False,  # noqa: E712
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_dimension_and_kpi(
        self, dimension_id: int, kpi_key, *, company_id: UUID
    ) -> Optional[WellnessDimensionKpiMapping]:
        stmt = select(WellnessDimensionKpiMapping).where(
            WellnessDimensionKpiMapping.dimension_id == dimension_id,
            WellnessDimensionKpiMapping.kpi_key == kpi_key,
            WellnessDimensionKpiMapping.company_id == company_id,
            WellnessDimensionKpiMapping.is_deleted == False,  # noqa: E712
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_for_dimension_with_kpi(
        self, dimension_id: int, *, company_id: UUID
    ) -> list[tuple[WellnessDimensionKpiMapping, Optional[str], Optional[float]]]:
        """Every non-deleted mapping for the (company, dimension) joined with
        the KPI catalog's `display_name` and `wi_weight`."""
        stmt = (
            select(
                WellnessDimensionKpiMapping,
                KPI.display_name,
                KPI.wi_weight,
            )
            .outerjoin(KPI, KPI.kpi_key == WellnessDimensionKpiMapping.kpi_key)
            .where(
                WellnessDimensionKpiMapping.dimension_id == dimension_id,
                WellnessDimensionKpiMapping.company_id == company_id,
                WellnessDimensionKpiMapping.is_deleted == False,  # noqa: E712
            )
            .order_by(
                WellnessDimensionKpiMapping.display_order.asc(),
                WellnessDimensionKpiMapping.id.asc(),
            )
        )
        res = await self.db.execute(stmt)
        return [(row[0], row[1], row[2]) for row in res.all()]
