from __future__ import annotations
from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from authentication_service.app.core.db import Base


class UserPolicy(Base):
    __tablename__ = "user_policies"
    __table_args__ = (
        UniqueConstraint("user_id", "policy_id", name="uq_user_policy"),
    )

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), primary_key=True)
    # FK to companies.id is enforced at the DB layer (cross-Base).
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
