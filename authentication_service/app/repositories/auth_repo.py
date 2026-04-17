from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from authentication_service.app.models.user import User


class AuthRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -----------------------------
    # GET BY ID
    # -----------------------------
    async def get_by_id(self, user_id: int) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalars().first()

