from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.challenge import Challenge


class ChallengeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, obj: Challenge) -> Challenge:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: Challenge) -> Challenge:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, challenge_key):
        stmt = select(Challenge).where(
            Challenge.challenge_key == challenge_key,
            Challenge.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_name_ci(self, name: str):
        stmt = select(Challenge).where(
            func.lower(Challenge.name) == func.lower(name),
            Challenge.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        search: str | None = None,
        is_active: bool | None = True,
        kpi_key=None,
        start_date=None,
        end_date=None,
    ):
        stmt = select(Challenge).where(Challenge.is_deleted == False)
        if is_active is not None:
            stmt = stmt.where(Challenge.is_active == is_active)
        if search:
            stmt = stmt.where(func.lower(Challenge.name).like(f"%{search.lower()}%"))
        if kpi_key or start_date or end_date:
            from config_service.app.models.kpi_challenge import KPIChallenge

            stmt = stmt.join(
                KPIChallenge,
                KPIChallenge.challenge_key == Challenge.challenge_key,
            ).where(
                KPIChallenge.is_deleted == False,
            )
            if kpi_key:
                stmt = stmt.where(KPIChallenge.kpi_key == kpi_key)
            if start_date is not None and end_date is not None:
                stmt = stmt.where(
                    KPIChallenge.start_date <= end_date,
                    or_(KPIChallenge.end_date.is_(None), KPIChallenge.end_date >= start_date),
                )
            elif start_date is not None:
                stmt = stmt.where(
                    or_(KPIChallenge.end_date.is_(None), KPIChallenge.end_date >= start_date)
                )
            elif end_date is not None:
                stmt = stmt.where(KPIChallenge.start_date <= end_date)
            stmt = stmt.distinct()

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Challenge.name.asc()).offset(skip).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total
