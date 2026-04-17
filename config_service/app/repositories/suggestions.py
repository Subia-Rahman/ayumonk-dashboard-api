from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.suggestion import Suggestion


class SuggestionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, obj: Suggestion) -> Suggestion:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: Suggestion) -> Suggestion:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, suggestion_id):
        stmt = select(Suggestion).where(
            Suggestion.id == suggestion_id,
            Suggestion.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        search: str | None = None,
        suggestion_type: str | None = None,
        is_active: bool | None = True,
    ):
        stmt = select(Suggestion).where(Suggestion.is_deleted == False)
        if is_active is not None:
            stmt = stmt.where(Suggestion.is_active == is_active)
        if suggestion_type:
            stmt = stmt.where(func.lower(Suggestion.suggestion_type) == suggestion_type.lower())
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                func.lower(Suggestion.title).like(like)
                | func.lower(Suggestion.description).like(like)
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Suggestion.created_at.desc()).offset(skip).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total
