from __future__ import annotations
import uuid

from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class BadgeMaster(Base, AuditMixin):
    __tablename__ = "badges_master"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    badge_key = Column(String(64), nullable=False, unique=True)
    label = Column(String(100), nullable=False)
    icon = Column(String(50), nullable=False)
    level = Column(String(20), nullable=False)
    trigger_type = Column(String(20), nullable=False)
    trigger_value = Column(Integer, nullable=False)
    # NULL = global badge (e.g. streak milestone, level cap). Non-NULL =
    # KPI-scoped (e.g. Hydration Hero Bronze fires only for Hydration KPI).
    kpi_key = Column(UUID(as_uuid=True), ForeignKey("kpis.kpi_key"), nullable=True)

    __table_args__ = (
        # The DB constraint is NULLS NOT DISTINCT (Postgres 15+). SQLAlchemy
        # treats this as informational only; the actual uniqueness is enforced
        # by the migration.
        UniqueConstraint(
            "trigger_type",
            "trigger_value",
            "kpi_key",
            name="uq_badges_master_trigger_scoped",
        ),
    )
