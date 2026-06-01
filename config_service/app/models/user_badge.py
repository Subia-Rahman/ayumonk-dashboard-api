import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class UserBadge(Base, AuditMixin):
    __tablename__ = "user_badges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # users lives in authentication_service; FK enforced only at DB level.
    user_id = Column(Integer, nullable=False)
    badge_id = Column(UUID(as_uuid=True), ForeignKey("badges_master.id"), nullable=False)
    earned_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "badge_id", name="uq_user_badges_user_badge"),
    )
