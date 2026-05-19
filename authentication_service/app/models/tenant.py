from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from authentication_service.app.core.db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False)
    code = Column(String(50), nullable=False, unique=True)
    domain = Column(String(150), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
