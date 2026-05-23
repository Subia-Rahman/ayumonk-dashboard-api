from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.cxo_metrics import (
    CxoMetricKpiMapping,
    CxoMetricMaster,
    CxoMetricSignalMapping,
)


class CxoMetricMasterRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active(self, *, company_id: UUID) -> list[CxoMetricMaster]:
        stmt = (
            select(CxoMetricMaster)
            .where(
                CxoMetricMaster.company_id == company_id,
                CxoMetricMaster.is_active == True,  # noqa: E712
            )
            .order_by(CxoMetricMaster.metric_code.asc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_by_id(self, metric_id: UUID) -> CxoMetricMaster | None:
        """Fetch by PK, excluding hard soft-deleted rows."""
        stmt = select(CxoMetricMaster).where(
            CxoMetricMaster.id == metric_id,
            CxoMetricMaster.is_deleted == False,  # noqa: E712
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_code(
        self, metric_code: str, *, company_id: UUID
    ) -> CxoMetricMaster | None:
        stmt = select(CxoMetricMaster).where(
            CxoMetricMaster.company_id == company_id,
            CxoMetricMaster.metric_code == metric_code,
            CxoMetricMaster.is_active == True,  # noqa: E712
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_code_any(
        self, metric_code: str, *, company_id: UUID
    ) -> CxoMetricMaster | None:
        """Includes soft-deleted rows. Used by the create endpoint to detect
        re-use of a metric_code that was previously deleted within a company."""
        stmt = select(CxoMetricMaster).where(
            CxoMetricMaster.company_id == company_id,
            CxoMetricMaster.metric_code == metric_code,
        ).execution_options(include_deleted=True)
        # Bypass the global soft-delete filter applied to AuditMixin selects.
        from sqlalchemy.orm import with_loader_criteria
        stmt = stmt.options(
            with_loader_criteria(CxoMetricMaster, lambda cls: True, include_aliases=True)
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def create(self, obj: CxoMetricMaster) -> CxoMetricMaster:
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj


class CxoMetricKpiMappingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, mapping_id: UUID) -> CxoMetricKpiMapping | None:
        stmt = select(CxoMetricKpiMapping).where(
            CxoMetricKpiMapping.id == mapping_id,
            CxoMetricKpiMapping.is_deleted == False,  # noqa: E712
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_active_for_metric(
        self, *, company_id: UUID, metric_id: UUID
    ) -> list[CxoMetricKpiMapping]:
        stmt = (
            select(CxoMetricKpiMapping)
            .where(
                CxoMetricKpiMapping.company_id == company_id,
                CxoMetricKpiMapping.metric_id == metric_id,
                CxoMetricKpiMapping.is_active == True,  # noqa: E712
            )
            .order_by(CxoMetricKpiMapping.weight.desc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def soft_delete_for_metric(
        self,
        *,
        company_id: UUID,
        metric_id: UUID,
        actor_user_id: int | None,
    ) -> int:
        """Soft-delete every active row for (company_id, metric_id). Returns
        the number of rows soft-deleted."""
        stmt = (
            update(CxoMetricKpiMapping)
            .where(
                CxoMetricKpiMapping.company_id == company_id,
                CxoMetricKpiMapping.metric_id == metric_id,
                CxoMetricKpiMapping.is_active == True,  # noqa: E712
            )
            .values(
                is_active=False,
                is_deleted=True,
                updated_at=func.now(),
                updated_by=actor_user_id,
            )
            .execution_options(synchronize_session=False)
        )
        res = await self.db.execute(stmt)
        return res.rowcount or 0


class CxoMetricSignalMappingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active_for_metric(
        self, *, company_id: UUID, metric_id: UUID
    ) -> list[CxoMetricSignalMapping]:
        stmt = (
            select(CxoMetricSignalMapping)
            .where(
                CxoMetricSignalMapping.company_id == company_id,
                CxoMetricSignalMapping.metric_id == metric_id,
                CxoMetricSignalMapping.is_active == True,  # noqa: E712
            )
            .order_by(CxoMetricSignalMapping.weight.desc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def soft_delete_for_metric(
        self,
        *,
        company_id: UUID,
        metric_id: UUID,
        actor_user_id: int | None,
    ) -> int:
        stmt = (
            update(CxoMetricSignalMapping)
            .where(
                CxoMetricSignalMapping.company_id == company_id,
                CxoMetricSignalMapping.metric_id == metric_id,
                CxoMetricSignalMapping.is_active == True,  # noqa: E712
            )
            .values(
                is_active=False,
                is_deleted=True,
                updated_at=func.now(),
                updated_by=actor_user_id,
            )
            .execution_options(synchronize_session=False)
        )
        res = await self.db.execute(stmt)
        return res.rowcount or 0
