from __future__ import annotations
import uuid

from sqlalchemy import Column, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class Department(Base, AuditMixin):
    __tablename__ = "departments"
    __table_args__ = (
        Index(
            "uq_departments_company_name_active",
            "company_id",
            "name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(150), nullable=False)
    description = Column(String, nullable=True)
    company_id = Column(
        UUID(as_uuid=True),
        ForeignKey("companies.id"),
        nullable=False,
        index=True,
    )
