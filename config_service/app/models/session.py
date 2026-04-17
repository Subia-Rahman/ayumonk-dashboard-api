import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class Session(Base, AuditMixin):
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_published = Column(Boolean, default=False, nullable=False)
    published_at = Column(DateTime, nullable=True)
    google_form_id = Column(String, nullable=True)
    google_form_responder_url = Column(String, nullable=True)
