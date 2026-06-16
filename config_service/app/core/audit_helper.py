from __future__ import annotations
"""Thin wrapper around ``AuditLogService.log()`` that never raises.

Phase-2 audit-log wiring fires from inside admin endpoint handlers, *after*
the main mutation has already committed via its own repo. We deliberately
do not want an audit-log failure (transient DB blip, JSON-serialisation
edge case, network) to fail the user-visible mutation it's recording —
the row is already persisted by the time we get here.

Use this helper instead of calling AuditLogService directly from a route
handler. For inside-transaction usage (e.g. inside ``async with
db.begin_nested():``), call ``AuditLogService(db).queue()`` directly, as
the seeder paths already do — those need to participate in the outer
transaction's commit/rollback.
"""

from logging import Logger
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.services.audit_log_service import AuditLogService


async def safe_audit_log(
    db: AsyncSession,
    *,
    user_id: int,
    tenant_id: Optional[UUID],
    action: str,
    entity: str,
    old_value=None,
    new_value=None,
    logger: Optional[Logger] = None,
) -> None:
    """Best-effort audit-log write.

    Args:
        db: The async session — same one the route handler used.
        user_id: Actor's user_id from the JWT.
        tenant_id: Company UUID this mutation affects, or None for
            platform-wide writes.
        action: Verb in CAPS, e.g. ``KPI_CHALLENGE_UPDATED``.
        entity: Table or logical entity name, e.g. ``kpi_challenges``.
        old_value / new_value: JSON-serialisable snapshots; UUIDs / dates /
            Decimals are coerced by ``AuditLogService._json_safe``.
        logger: Optional logger. When provided, audit failures are
            ``logger.exception``-logged so they surface in dashboards
            without raising.
    """
    try:
        await AuditLogService(db).log(
            user_id=user_id,
            tenant_id=tenant_id,
            action=action,
            entity=entity,
            old_value=old_value,
            new_value=new_value,
        )
    except Exception:
        # Audit failures must not surface — the mutation already succeeded.
        if logger is not None:
            logger.exception(
                "AUDIT_LOG_FAILED | action=%s | entity=%s | user_id=%s",
                action,
                entity,
                user_id,
            )
