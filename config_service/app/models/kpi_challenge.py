from __future__ import annotations
import uuid

from sqlalchemy import Column, Date, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class KPIChallenge(Base, AuditMixin):
    __tablename__ = "kpi_challenges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=True,
        index=True,
    )
    kpi_key = Column(UUID(as_uuid=True), ForeignKey("kpis.kpi_key"), nullable=False)
    challenge_key = Column(UUID(as_uuid=True), ForeignKey("challenges.challenge_key"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
