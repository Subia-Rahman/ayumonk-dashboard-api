from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, Text, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from authentication_service.app.core.db import Base


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (
        CheckConstraint(
            "scope IS NULL OR scope IN ('global', 'tenant', 'department', 'self')",
            name="ck_policy_scope",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    module = Column(String(50), nullable=False)
    scope = Column(String(20), nullable=True)
    conditions = Column(JSON, nullable=True)
    condition_json = Column(JSON, nullable=False)
    effect = Column(String(10), nullable=False)
    # FK to companies.id is enforced at the DB layer (cross-Base).
    # NULL = platform-level policy (e.g. Global Access for platform admins).
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
