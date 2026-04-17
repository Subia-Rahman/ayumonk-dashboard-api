import uuid
from sqlalchemy import Column, Date, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class UserChallengeCompletion(Base, AuditMixin):
    __tablename__ = "user_challenge_completions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, nullable=False)
    challenge_id = Column(UUID(as_uuid=True), ForeignKey("challenges.challenge_key"), nullable=False)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False)
    completion_date = Column(Date, nullable=False)
    value_logged = Column(Integer, nullable=True)
    xp_earned = Column(Integer, nullable=False, default=0)
