from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.models.audit_log import AuditLog


class AuditLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, log: AuditLog) -> AuditLog:
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log
