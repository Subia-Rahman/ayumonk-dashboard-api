from __future__ import annotations
import uuid
from sqlalchemy import Column, Integer, ForeignKey,String
from sqlalchemy.dialects.postgresql import UUID
from config_service.app.core.db import Base
from config_service.app.core.audit.mixin import AuditMixin



class KPIScoring(Base, AuditMixin):
    __tablename__ = "kpi_scoring"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=True,
        index=True,
    )
    question_id = Column(UUID(as_uuid=True), ForeignKey("kpi_questions.id"))
    option_number = Column(Integer)  # 1..5
    score = Column(Integer)
    option_text = Column(String)
