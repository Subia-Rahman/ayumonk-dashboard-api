from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from authentication_service.app.core.db import Base


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (
        # Per-tenant uniqueness: no two roles with the same name within a tenant.
        UniqueConstraint("name", "tenant_id", name="uq_role_name_per_tenant"),
        # Platform-wide uniqueness: standard SQL UNIQUE treats NULLs as distinct,
        # so we need a partial index to prevent two "Super Admin" rows with
        # tenant_id IS NULL.
        Index(
            "uq_role_name_platform",
            "name",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)
    # tenant_id stores companies.id; the FK is enforced at the DB layer
    # via the rbac_3_layer.sql migration (cross-Base FKs cannot be
    # resolved by SQLAlchemy because companies belongs to config_service's
    # declarative metadata).
    # NULL = platform-wide role (Super Admin, Ayumonk Admin).
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
