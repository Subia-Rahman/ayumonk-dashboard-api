import uuid

from sqlalchemy import Column, Date, ForeignKey, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class KPI(Base, AuditMixin):
    __tablename__ = "kpis"
    kpi_key = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    display_name = Column(String, nullable=False)
    theme_key = Column(ForeignKey("themes.theme_key"))
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    domain_category = Column(String(20))
    wi_weight = Column(Numeric(4, 2), server_default=text("0.10"))
