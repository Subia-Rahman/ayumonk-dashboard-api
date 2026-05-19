import uuid
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base
from sqlalchemy import Column, ForeignKey, Integer, String, DateTime, Boolean, SmallInteger, Enum, func

class Company(Base,AuditMixin):
    __tablename__ = "companies"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_name = Column(String)
    industry = Column(String)
    size_bucket = Column(String)
    email = Column(String)
    phone = Column(String)
    location_id = Column(
        UUID(as_uuid=True),
        ForeignKey("locations.id"),
        nullable=True,
        index=True,
    )
    no_of_employees = Column(Integer)
