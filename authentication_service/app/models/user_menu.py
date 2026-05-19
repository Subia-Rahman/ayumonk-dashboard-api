from sqlalchemy import Column, Integer, ForeignKey, Boolean, String, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from authentication_service.app.core.db import Base


class UserMenu(Base):
    __tablename__ = "user_menus"
    __table_args__ = (
        CheckConstraint(
            "access_level IN ('none', 'view', 'full')",
            name="ck_user_menu_access_level",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    menu_id = Column(Integer, ForeignKey("menus.id"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    # FK to companies.id is enforced at the DB layer (cross-Base).
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    access_level = Column(
        String(10),
        nullable=False,
        default="view",
        server_default="view",
    )
