import uuid

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, String, Time, text
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class ReminderSettings(Base, AuditMixin):
    __tablename__ = "reminder_settings"
    __table_args__ = (
        Index(
            "uq_reminder_settings_user_active",
            "user_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index("ix_reminder_settings_user_id", "user_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("company_users.id"),
        nullable=False,
    )

    is_enabled = Column(Boolean, nullable=False, default=True)

    email_enabled = Column(Boolean, nullable=False, default=True)
    push_enabled = Column(Boolean, nullable=False, default=False)
    whatsapp_enabled = Column(Boolean, nullable=False, default=False)

    reminder_time = Column(Time, nullable=False)
    timezone = Column(String(64), nullable=False, default="UTC")

    daily_challenge = Column(Boolean, nullable=False, default=True)
    streak_alert = Column(Boolean, nullable=False, default=True)
    program_ending = Column(Boolean, nullable=False, default=True)
    new_program = Column(Boolean, nullable=False, default=True)
    badge_milestone = Column(Boolean, nullable=False, default=True)

    snooze_until = Column(DateTime, nullable=True)

    # Last user-local date a reminder was dispatched. Used by the scheduler
    # to ensure at-most-once delivery per user per day.
    last_dispatched_on = Column(Date, nullable=True)
