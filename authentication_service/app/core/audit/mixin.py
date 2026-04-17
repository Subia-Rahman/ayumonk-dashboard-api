from sqlalchemy import Column, DateTime, Boolean, Integer
from datetime import datetime


class AuditMixin:
    """
    Common audit fields for all tables.
    """

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
