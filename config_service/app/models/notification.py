import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class Notification(Base, AuditMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "ix_notifications_user_read_created",
            "user_id",
            "is_read",
            "created_at",
        ),
        Index("ix_notifications_company_id", "company_id"),
        Index("ix_notifications_type", "type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("company_users.id"),
        nullable=False,
    )
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=True,
    )

    type = Column(String(64), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=True)
    icon = Column(String(64), nullable=True)

    action_type = Column(String(64), nullable=True)
    action_payload = Column(JSONB, nullable=True)

    is_read = Column(Boolean, nullable=False, default=False)
    read_at = Column(DateTime, nullable=True)
    dismissed_at = Column(DateTime, nullable=True)
    snooze_until = Column(DateTime, nullable=True)
