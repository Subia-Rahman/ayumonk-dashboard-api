from __future__ import annotations
from sqlalchemy import Column, Integer, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from authentication_service.app.core.db import Base


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    role_id = Column(Integer, ForeignKey("roles.id"), primary_key=True)
    permission_id = Column(Integer, ForeignKey("permissions.id"), primary_key=True)
    # FK to companies.id is enforced at the DB layer (cross-Base).
    # NULL = platform-wide grant (e.g. Super Admin / Ayumonk Admin).
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    is_override = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    is_granted = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
