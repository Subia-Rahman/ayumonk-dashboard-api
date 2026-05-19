from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.models.vendor import Vendor


class VendorRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_user_id(self, user_id: int):
        result = await self.db.execute(
            select(Vendor).where(Vendor.user_id == user_id)
        )
        return result.scalars().first()
