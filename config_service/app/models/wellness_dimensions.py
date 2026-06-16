from __future__ import annotations
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class WellnessDimension(Base, AuditMixin):
    """Per-company catalog of wellness dimensions (e.g. 'sleep', 'stress').
    Tenant-scoped: `dimension_key` is unique within a company, not globally."""

    __tablename__ = "wellness_dimension"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "dimension_key",
            name="uq_wellness_dimension_company_key",
        ),
        Index("ix_wellness_dimension_company_id", "company_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    dimension_key = Column(String(50), nullable=False)
    dimension_label = Column(String(100), nullable=False)
    display_order = Column(SmallInteger, nullable=False, default=1)


class WellnessDimensionKpiMapping(Base, AuditMixin):
    """Per-company mapping of KPIs to a wellness dimension with a per-KPI
    weight. `company_id` duplicates the parent dimension's tenant so the
    mapping table can be queried directly without joining wellness_dimension."""

    __tablename__ = "wellness_dimension_kpi_mapping"
    __table_args__ = (
        CheckConstraint("weight > 0", name="ck_wellness_mapping_weight_positive"),
        UniqueConstraint(
            "dimension_id",
            "kpi_key",
            name="uq_wellness_dimension_kpi",
        ),
        Index(
            "ix_wellness_dimension_kpi_mapping_dimension",
            "dimension_id",
        ),
        Index(
            "ix_wellness_dimension_kpi_mapping_company_id",
            "company_id",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    dimension_id = Column(
        Integer,
        ForeignKey("wellness_dimension.id", ondelete="CASCADE"),
        nullable=False,
    )
    kpi_key = Column(
        UUID(as_uuid=True),
        ForeignKey("kpis.kpi_key"),
        nullable=False,
    )
    weight = Column(Numeric(4, 2), nullable=False, default=1.00)
    display_order = Column(SmallInteger, nullable=False, default=1)
