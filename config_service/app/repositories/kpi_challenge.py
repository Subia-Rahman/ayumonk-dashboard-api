from __future__ import annotations
from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.challenge import Challenge
from config_service.app.models.kpi_challenge import KPIChallenge


class KPIChallengeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, obj: KPIChallenge) -> KPIChallenge:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def create_many(self, objs: list[KPIChallenge]) -> list[KPIChallenge]:
        self.db.add_all(objs)
        await self.db.commit()
        for obj in objs:
            await self.db.refresh(obj)
        return objs

    async def list_by_challenge(self, challenge_key):
        stmt = (
            select(KPIChallenge)
            .where(
                KPIChallenge.challenge_key == challenge_key,
                KPIChallenge.is_deleted == False,
            )
            .order_by(KPIChallenge.start_date.asc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def list_by_kpi_and_range(
        self,
        *,
        kpi_key,
        start_date: date | None,
        end_date: date | None,
    ):
        stmt = (
            select(KPIChallenge, Challenge)
            .join(Challenge, Challenge.challenge_key == KPIChallenge.challenge_key)
            .where(
                KPIChallenge.kpi_key == kpi_key,
                KPIChallenge.is_deleted == False,
                Challenge.is_deleted == False,
            )
        )

        if start_date is not None and end_date is not None:
            stmt = stmt.where(
                KPIChallenge.start_date <= end_date,
                or_(KPIChallenge.end_date.is_(None), KPIChallenge.end_date >= start_date),
            )
        elif start_date is not None:
            stmt = stmt.where(
                or_(KPIChallenge.end_date.is_(None), KPIChallenge.end_date >= start_date),
            )
        elif end_date is not None:
            stmt = stmt.where(KPIChallenge.start_date <= end_date)

        stmt = stmt.order_by(KPIChallenge.start_date.asc())
        res = await self.db.execute(stmt)
        return res.all()

    async def list_active_by_date(self, target_date: date):
        stmt = (
            select(KPIChallenge, Challenge)
            .join(Challenge, Challenge.challenge_key == KPIChallenge.challenge_key)
            .where(
                KPIChallenge.is_deleted == False,
                Challenge.is_deleted == False,
                KPIChallenge.start_date <= target_date,
                or_(KPIChallenge.end_date.is_(None), KPIChallenge.end_date >= target_date),
            )
            .order_by(KPIChallenge.start_date.asc())
        )
        res = await self.db.execute(stmt)
        return res.all()

    async def get_by_id(self, mapping_id, company_id=None) -> KPIChallenge | None:
        """Fetch a single non-deleted kpi_challenges row by id, optionally
        scoped to a tenant. Returns None when missing or out-of-scope."""
        stmt = select(KPIChallenge).where(
            KPIChallenge.id == mapping_id,
            KPIChallenge.is_deleted == False,
        )
        if company_id is not None:
            stmt = stmt.where(KPIChallenge.company_id == company_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def update(self, mapping: KPIChallenge) -> KPIChallenge:
        """Persist in-place edits on a KPIChallenge already attached to
        the session. Caller is expected to have mutated the fields
        already; this commits and refreshes."""
        await self.db.commit()
        await self.db.refresh(mapping)
        return mapping

    async def soft_delete(self, mapping: KPIChallenge) -> KPIChallenge:
        """Mark the mapping as deleted + inactive. Returns the refreshed
        row so callers can snapshot the final state into an audit log."""
        mapping.is_deleted = True
        mapping.is_active = False
        await self.db.commit()
        await self.db.refresh(mapping)
        return mapping
