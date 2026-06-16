from __future__ import annotations
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.models.revoked_token import RevokedToken


class RevokedTokenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def exists(self, jti: str) -> bool:
        result = await self.db.execute(
            select(RevokedToken.id).where(RevokedToken.jti == jti)
        )
        return result.scalar_one_or_none() is not None

    async def add(
        self,
        *,
        jti: str,
        user_id: int | None,
        expires_at: datetime,
    ) -> RevokedToken:
        record = RevokedToken(jti=jti, user_id=user_id, expires_at=expires_at)
        self.db.add(record)
        try:
            await self.db.commit()
        except IntegrityError:
            # Concurrent revocation of the same jti is a no-op success.
            await self.db.rollback()
            existing = await self.db.execute(
                select(RevokedToken).where(RevokedToken.jti == jti)
            )
            return existing.scalar_one()
        await self.db.refresh(record)
        return record

    async def purge_expired(self) -> int:
        result = await self.db.execute(
            delete(RevokedToken).where(RevokedToken.expires_at < datetime.utcnow())
        )
        await self.db.commit()
        return result.rowcount or 0
