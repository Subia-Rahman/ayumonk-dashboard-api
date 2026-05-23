import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class CxoMetricMaster(Base, AuditMixin):
    """Per-company metric catalog (PRODUCTIVITY / ENGAGEMENT / ABSENTEEISM
    plus any company-specific additions). `metric_code` is unique within a
    company, not globally."""

    __tablename__ = "cxo_metric_master"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "metric_code",
            name="uq_company_metric_code",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_code = Column(String(30), nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)


class CxoMetricKpiMapping(Base, AuditMixin):
    """Per-company KPI weights for WEIGHTED_AVG / DEFICIT_SUM metrics."""

    __tablename__ = "cxo_metric_kpi_mapping"
    __table_args__ = (
        CheckConstraint("weight >= 0", name="ck_weight_nonneg"),
        UniqueConstraint(
            "company_id",
            "metric_id",
            "kpi_key",
            name="uq_company_metric_kpi",
        ),
        Index(
            "idx_cxo_mapping_lookup",
            "company_id",
            "metric_id",
            postgresql_where=text("is_active AND NOT is_deleted"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_id = Column(
        UUID(as_uuid=True),
        ForeignKey("cxo_metric_master.id", ondelete="CASCADE"),
        nullable=False,
    )
    kpi_key = Column(
        UUID(as_uuid=True),
        ForeignKey("kpis.kpi_key"),
        nullable=False,
    )
    weight = Column(Numeric(4, 3), nullable=False)


class CxoMetricSignalMapping(Base, AuditMixin):
    """Per-company composite-signal weights (for ENGAGEMENT)."""

    __tablename__ = "cxo_metric_signal_mapping"
    __table_args__ = (
        CheckConstraint(
            "signal_code IN ('WELLNESS_INDEX','CHALLENGE_RATE_30D','FORM_RATE_90D','MOOD_AVG')",
            name="ck_signal_code",
        ),
        CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_signal_weight_range",
        ),
        UniqueConstraint(
            "company_id",
            "metric_id",
            "signal_code",
            name="uq_company_metric_signal",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    metric_id = Column(
        UUID(as_uuid=True),
        ForeignKey("cxo_metric_master.id", ondelete="CASCADE"),
        nullable=False,
    )
    signal_code = Column(String(40), nullable=False)
    weight = Column(Numeric(4, 3), nullable=False)
