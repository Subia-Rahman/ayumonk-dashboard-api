from __future__ import annotations
import uuid

from sqlalchemy import Column, ForeignKey, Index, Integer, String, text
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
    # Legacy free-text department label (kept for backward compatibility).
    department = Column(String)
    gender = Column(String)
    email = Column(String)
    phone = Column(String)
    age_band = Column(String)
    company_id = Column(UUID(as_uuid=True), ForeignKey("companies.id"))

    # Tenant-scoped department FK; required when the assigned role's policy
    # has scope='department'. Enforced in the service layer.
    department_id = Column(
        UUID(as_uuid=True),
        ForeignKey("departments.id"),
        nullable=True,
        index=True,
    )

    # Single RBAC role per company user. roles.id is INTEGER in
    # authentication_service (cross-Base FK enforced at the DB layer via
    # the migration script).
    role_id = Column(Integer, nullable=True, index=True)
