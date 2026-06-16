from __future__ import annotations
from sqlalchemy import Column, Integer, String, Index
from authentication_service.app.core.db import Base


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = (
        Index("ix_permissions_codename", "codename", unique=True),
        Index("ix_permissions_resource_action", "resource", "action"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    codename = Column(String(150), nullable=True)
    resource = Column(String(50), nullable=True)
    module = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
