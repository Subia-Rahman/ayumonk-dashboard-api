from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.badge_master import BadgeMaster


class BadgeMasterRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, obj: BadgeMaster) -> BadgeMaster:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: BadgeMaster) -> BadgeMaster:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, badge_id):
        stmt = select(BadgeMaster).where(
            BadgeMaster.id == badge_id,
            BadgeMaster.is_deleted == False,  # noqa: E712
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_badge_key(self, badge_key: str):
        stmt = select(BadgeMaster).where(
            func.lower(BadgeMaster.badge_key) == badge_key.lower(),
            BadgeMaster.is_deleted == False,  # noqa: E712
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_by_trigger(self, *, trigger_type: str, trigger_value: int, kpi_key):
        """Find a badge with the same (trigger_type, trigger_value, kpi_key)
        triple. Used by the service to enforce the DB unique constraint
        before INSERT so the user gets a clean 409 instead of a 500."""
        stmt = select(BadgeMaster).where(
            BadgeMaster.trigger_type == trigger_type,
            BadgeMaster.trigger_value == trigger_value,
            BadgeMaster.is_deleted == False,  # noqa: E712
        )
        if kpi_key is None:
            stmt = stmt.where(BadgeMaster.kpi_key.is_(None))
        else:
            stmt = stmt.where(BadgeMaster.kpi_key == kpi_key)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        kpi_key=None,
        trigger_type: str | None = None,
        level: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ):
        stmt = select(BadgeMaster).where(BadgeMaster.is_deleted == False)  # noqa: E712
        if kpi_key is not None:
            stmt = stmt.where(BadgeMaster.kpi_key == kpi_key)
        if trigger_type is not None:
            stmt = stmt.where(BadgeMaster.trigger_type == trigger_type)
        if level is not None:
            stmt = stmt.where(BadgeMaster.level == level)
        if is_active is not None:
            stmt = stmt.where(BadgeMaster.is_active == is_active)
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(BadgeMaster.badge_key).like(like),
                    func.lower(BadgeMaster.label).like(like),
                )
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = (
            stmt.order_by(
                BadgeMaster.kpi_key.asc().nullsfirst(),
                BadgeMaster.trigger_type.asc(),
                BadgeMaster.trigger_value.asc(),
            )
            .offset(skip)
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total
