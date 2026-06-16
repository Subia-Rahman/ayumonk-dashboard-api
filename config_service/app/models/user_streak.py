from __future__ import annotations
import uuid

from sqlalchemy import Column, Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class UserStreak(Base, AuditMixin):
    __tablename__ = "user_streaks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # NOTE: users lives in authentication_service; no ORM-level FK across
    # service boundaries. The DB-level FK is enforced by the migration.
    user_id = Column(Integer, nullable=False)
    challenge_id = Column(UUID(as_uuid=True), ForeignKey("challenges.challenge_key"), nullable=False)
    current_streak = Column(Integer, nullable=False, default=0)
    longest_streak = Column(Integer, nullable=False, default=0)
    last_completion_date = Column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "challenge_id", name="uq_user_streaks_user_challenge"),
    )
