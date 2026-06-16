from __future__ import annotations
"""SQLAlchemy model for ``reminder_log``.

Durable, append-only record of every reminder the dispatcher fires.
One row per (user, reminder_type, channel) attempt.

Distinct from ``notification`` — that table is user-facing (powers the
bell icon). reminder_log is engine-side bookkeeping for the
ReminderSettings "Recent sends" panel + debugging.

See migration ``scripts/migrations/reminder_log.sql`` for the
authoritative schema. Free-text on ``reminder_type`` / ``status`` so
new reminder types ship without a CHECK constraint migration.
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class ReminderLog(Base, AuditMixin):
    __tablename__ = "reminder_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("company_users.id"), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    reminder_type = Column(String(64), nullable=False)
    channel = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False)
    details = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=False, default=datetime.utcnow)
