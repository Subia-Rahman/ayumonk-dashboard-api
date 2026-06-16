from __future__ import annotations
import uuid

from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class Location(Base, AuditMixin):
    __tablename__ = "locations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    name_normalized = Column(String, nullable=False, unique=True, index=True)
