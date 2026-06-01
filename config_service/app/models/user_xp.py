import uuid

from sqlalchemy import Column, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class UserXp(Base, AuditMixin):
    __tablename__ = "user_xp"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # users lives in authentication_service; FK enforced only at DB level.
    user_id = Column(Integer, nullable=False, unique=True)
    total_xp = Column(Integer, nullable=False, default=0)
    xp_this_week = Column(Integer, nullable=False, default=0)
    current_level = Column(Integer, nullable=False, default=1)
    level_label = Column(String(40), nullable=False, default="Seedling")
