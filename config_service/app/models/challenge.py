import uuid

from sqlalchemy import Boolean, Column, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class Challenge(Base, AuditMixin):
    __tablename__ = "challenges"

    challenge_key = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    challenge_type = Column(String(20), nullable=False)
    target_value = Column(Integer, nullable=True)
    xp_reward = Column(SmallInteger, nullable=False, default=20)
    icon = Column(String(50), nullable=True)
    is_daily = Column(Boolean, nullable=False, default=True)
