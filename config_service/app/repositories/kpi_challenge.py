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
