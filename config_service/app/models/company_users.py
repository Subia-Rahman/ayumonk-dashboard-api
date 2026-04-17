import uuid

from sqlalchemy import Column, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class CompanyUser(Base, AuditMixin):
    __tablename__ = "company_users"
    __table_args__ = (
        Index(
            "uq_company_users_company_email_active",
            "company_id",
            "email",
            unique=True,
            postgresql_where=text("is_deleted = false"),
        ),
        Index(
            "uq_company_users_company_emp_id_active",
            "company_id",
            "emp_id",
            unique=True,
            postgresql_where=text("is_deleted = false AND emp_id IS NOT NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    emp_id = Column(String)
    full_name = Column(String)
    department = Column(String)
    gender = Column(String)
    email = Column(String)
    phone = Column(String)
    location = Column(String)
    age_band = Column(String)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"))
