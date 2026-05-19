from sqlalchemy import Column, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from authentication_service.app.core.db import Base


class RolePolicy(Base):
    __tablename__ = "role_policies"
    __table_args__ = (
        UniqueConstraint("role_id", "policy_id", name="uq_role_policy"),
    )

    role_id = Column(Integer, ForeignKey("roles.id"), primary_key=True)
    policy_id = Column(Integer, ForeignKey("policies.id"), primary_key=True)
    # FK to companies.id is enforced at the DB layer (cross-Base).
    # NULL = platform-wide grant (e.g. Super Admin / Ayumonk Admin).
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
