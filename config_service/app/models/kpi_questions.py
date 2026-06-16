from __future__ import annotations
import uuid

from sqlalchemy import Column, ForeignKey, Index, String, Boolean, text
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class KPIQuestion(Base, AuditMixin):
    __tablename__ = "kpi_questions"
    __table_args__ = (
        Index(
            "uq_kpi_questions_company_code_active",
            "company_id",
            "question_code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True)
    theme = Column(UUID(as_uuid=True))
    kpi = Column(UUID(as_uuid=True))
    question_code = Column(String)
    question_text = Column(String)
    reverse_code = Column(Boolean, default=False)
