from __future__ import annotations
from datetime import date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.user_challenge_completion import UserChallengeCompletion


class UserChallengeCompletionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, obj: UserChallengeCompletion) -> UserChallengeCompletion:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: UserChallengeCompletion) -> UserChallengeCompletion:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def get_by_user_challenge_date(self, user_id, challenge_id, completion_date: date):
        stmt = select(UserChallengeCompletion).where(
            UserChallengeCompletion.user_id == user_id,
            UserChallengeCompletion.challenge_id == challenge_id,
            UserChallengeCompletion.completion_date == completion_date,
            UserChallengeCompletion.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_by_user_date(self, user_id, completion_date: date):
        stmt = select(UserChallengeCompletion).where(
            UserChallengeCompletion.user_id == user_id,
            UserChallengeCompletion.completion_date == completion_date,
            UserChallengeCompletion.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())
