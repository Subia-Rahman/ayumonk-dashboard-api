from __future__ import annotations
import datetime
import uuid
from sqlalchemy.dialects.postgresql import UUID
from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base
from sqlalchemy import Column, String, DateTime, Boolean, Index
from sqlalchemy.dialects.postgresql import JSONB

class EmployeeFormResponse(Base, AuditMixin):
    __tablename__ = "employee_form_response"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(String)
    form_id = Column(String)
    employee_email = Column(String)
    response_id = Column(String, unique=True)
    submitted_at = Column(DateTime)

    is_latest = Column(Boolean, default=True)
    raw_payload = Column(JSONB)

    __table_args__ = (
        Index(
            "idx_active_form_user",
            "form_id",
            "employee_email",
            postgresql_where=(is_latest == True)
        ),
    )