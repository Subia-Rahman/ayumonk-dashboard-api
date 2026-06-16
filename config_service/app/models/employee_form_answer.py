from __future__ import annotations
import uuid
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base
from sqlalchemy import Column, Integer, String

class EmployeeFormAnswer(Base,AuditMixin):
    __tablename__ = "employee_form_answer"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    response_id = Column(String)
    question_code = Column(String)
    selected_option = Column(String)
    score = Column(Integer)
