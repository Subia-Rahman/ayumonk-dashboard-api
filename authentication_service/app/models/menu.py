from __future__ import annotations
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID
from authentication_service.app.core.db import Base


class Menu(Base):
    __tablename__ = "menus"
    __table_args__ = (
        Index("ix_menus_tenant_slug", "tenant_id", "slug"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), nullable=True)
    path = Column(String(200), nullable=True)
    parent_id = Column(Integer, ForeignKey("menus.id"), nullable=True)
    icon = Column(String(100), nullable=True)
    order_no = Column(Integer, default=0, nullable=False)
    # FK to companies.id is enforced at the DB layer (cross-Base).
    # NULL = platform-level menu (visible only to platform admins).
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
