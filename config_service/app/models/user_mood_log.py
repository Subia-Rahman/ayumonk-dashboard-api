"""SQLAlchemy model for ``user_mood_log``.

Append-only daily 5-emoji mood check-in history. POST /api/v1/wellness/mood
inserts one row per tap. score is 1-5 (1=😞 / 2=😕 / 3=😐 / 4=🙂 / 5=😄).
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class UserMoodLog(Base, AuditMixin):
    __tablename__ = "user_mood_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_email = Column(String, nullable=False)
    company_id = Column(UUID(as_uuid=True), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("company_users.id"), nullable=True)
    score = Column(SmallInteger, nullable=False)
    logged_at = Column(DateTime, nullable=False, default=datetime.utcnow)
