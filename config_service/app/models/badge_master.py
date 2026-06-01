import uuid

from sqlalchemy import Column, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class BadgeMaster(Base, AuditMixin):
    __tablename__ = "badges_master"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    badge_key = Column(String(64), nullable=False, unique=True)
    label = Column(String(100), nullable=False)
    icon = Column(String(50), nullable=False)
    level = Column(String(20), nullable=False)
    trigger_type = Column(String(20), nullable=False)
    trigger_value = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("trigger_type", "trigger_value", name="uq_badges_master_trigger"),
    )
