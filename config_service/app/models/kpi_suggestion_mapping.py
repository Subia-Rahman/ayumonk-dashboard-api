import uuid

from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class KPISuggestionMapping(Base, AuditMixin):
    __tablename__ = "kpi_suggestion_mappings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kpi_key = Column(UUID(as_uuid=True), ForeignKey("kpis.kpi_key"), nullable=False)
    trigger_mode = Column(String(20), nullable=False)
    risk_level = Column(String(20), nullable=True)
    question_key = Column(UUID(as_uuid=True), ForeignKey("kpi_questions.id"), nullable=True)
    score_threshold_below = Column(Integer, nullable=True)
    score_threshold_above = Column(Integer, nullable=True)
    kpi_score_below = Column(Integer, nullable=True)
    suggestion_id = Column(UUID(as_uuid=True), ForeignKey("suggestions.id"), nullable=False)
    priority = Column(Integer, nullable=False, default=1)
