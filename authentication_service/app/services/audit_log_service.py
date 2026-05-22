from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.models.audit_log import AuditLog
from authentication_service.app.repositories.audit_log_repo import AuditLogRepository


def _json_safe(value):
    """Recursively coerce values to types Postgres' JSON encoder accepts.
    UUIDs / datetimes / Decimals / Enums become their string forms; dicts
    and lists are walked. Used so callers can pass raw model_dump() output
    without remembering to use mode="json"."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


class AuditLogService:
    def __init__(self, db: AsyncSession):
        self.repo = AuditLogRepository(db)

    async def log(
        self,
        user_id: int,
        tenant_id: UUID,
        action: str,
        entity: str,
        old_value=None,
        new_value=None,
    ):
        return await self.repo.create(
            AuditLog(
                user_id=user_id,
                tenant_id=tenant_id,
                action=action,
                entity=entity,
                old_value=_json_safe(old_value),
                new_value=_json_safe(new_value),
            )
        )

    def queue(
        self,
        user_id: int,
        tenant_id: UUID,
        action: str,
        entity: str,
        old_value=None,
        new_value=None,
    ) -> AuditLog:
        """Add an audit log row to the session WITHOUT committing.

        Use this when you already own a transaction (e.g. inside
        ``async with db.begin_nested():``). The plain ``log()`` method
        commits internally, which closes the outer transaction and breaks
        the surrounding savepoint context manager.
        """
        row = AuditLog(
            user_id=user_id,
            tenant_id=tenant_id,
            action=action,
            entity=entity,
            old_value=_json_safe(old_value),
            new_value=_json_safe(new_value),
        )
        self.repo.db.add(row)
        return row
