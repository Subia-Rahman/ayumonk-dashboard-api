from __future__ import annotations
from sqlalchemy import Column, Integer, ForeignKey, String, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from authentication_service.app.core.db import Base


class RoleMenu(Base):
    __tablename__ = "role_menus"
    __table_args__ = (
        UniqueConstraint("role_id", "menu_id", name="uq_role_menu"),
        CheckConstraint(
            "access_level IN ('none', 'view', 'full')",
            name="ck_role_menu_access_level",
        ),
    )

    role_id = Column(Integer, ForeignKey("roles.id"), primary_key=True)
    menu_id = Column(Integer, ForeignKey("menus.id"), primary_key=True)
    # FK to companies.id is enforced at the DB layer (cross-Base).
    # NULL = platform-wide grant (e.g. Super Admin / Ayumonk Admin).
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    access_level = Column(
        String(10),
        nullable=False,
        default="view",
        server_default="view",
    )
