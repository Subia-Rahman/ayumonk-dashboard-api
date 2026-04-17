import uuid
from sqlalchemy import Column, String, Boolean
from sqlalchemy.dialects.postgresql import UUID
from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base
import uuid

class KPIQuestion(Base,AuditMixin):
    __tablename__ = "kpi_questions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    theme = Column(UUID(as_uuid=True))  # if this is supposed to be a UUID
    kpi = Column(UUID(as_uuid=True))
    question_code = Column(String, unique=True)
    question_text = Column(String)
    reverse_code = Column(Boolean, default=False)

