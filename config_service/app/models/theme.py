from __future__ import annotations
from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base
from sqlalchemy import Column, ForeignKey, Integer, String
import uuid
from sqlalchemy.dialects.postgresql import UUID

class Theme(Base, AuditMixin):
    __tablename__ = "themes"
    theme_key = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    theme_display_name = Column(String)
    description = Column(String)
    duration_days = Column(Integer)
    target_audience = Column(String)
