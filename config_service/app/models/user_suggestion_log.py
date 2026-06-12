"""SQLAlchemy model for ``user_suggestion_log``.

Durable record of what the two-tier suggestion engine served to each
employee after every wellness-form submission, plus what the employee
did with it (done / skipped / saved).

Populated synchronously by ``SuggestionEngineService.compute_and_persist``
inside the form-submission write path, right after the WI row is
written. Read by ``GET /api/v1/suggestions/my`` and mutated by
``POST /api/v1/suggestions/{log_id}/action``.

See migration ``scripts/migrations/user_suggestion_log.sql`` for the
authoritative schema + constraints (trigger_mode CHECK, action CHECK,
response/suggestion UNIQUE).
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class UserSuggestionLog(Base, AuditMixin):
    __tablename__ = "user_suggestion_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    response_id = Column(
        String, ForeignKey("employee_form_response.response_id"), nullable=False
    )
    employee_email = Column(String, nullable=False)
    company_id = Column(String, nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("company_users.id"), nullable=True)
    suggestion_id = Column(UUID(as_uuid=True), ForeignKey("suggestions.id"), nullable=False)
    kpi_key = Column(UUID(as_uuid=True), ForeignKey("kpis.kpi_key"), nullable=True)
    trigger_mode = Column(String(20), nullable=False)
    priority = Column(SmallInteger, nullable=False, default=1)
    shown_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    action = Column(String(20), nullable=True)
    actioned_at = Column(DateTime, nullable=True)
