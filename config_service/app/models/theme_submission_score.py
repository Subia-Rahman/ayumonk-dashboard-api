"""SQLAlchemy model for ``theme_submission_scores``.

One row per wellness-form submission, populated synchronously inside
``sessions.submit_form`` / ``employee_form.process_submission``.

See migration ``scripts/migrations/wellness_index_and_mood.sql`` for the
authoritative schema + constraints (risk_level CHECK, response_id UNIQUE,
score range 0-100).
"""

import uuid

from sqlalchemy import Column, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID

from config_service.app.core.audit.mixin import AuditMixin
from config_service.app.core.db import Base


class ThemeSubmissionScore(Base, AuditMixin):
    __tablename__ = "theme_submission_scores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # employee_form_response.response_id is VARCHAR + UNIQUE — anchor as FK
    # string so the relationship matches without a cast.
    response_id = Column(
        String, ForeignKey("employee_form_response.response_id"), nullable=False
    )
    # Matches employee_form_response.company_id (also VARCHAR — that table
    # historically holds legacy non-UUID values e.g. "COMPANY_123").
    company_id = Column(String, nullable=True)
    employee_email = Column(String, nullable=False)
    theme_key = Column(UUID(as_uuid=True), ForeignKey("themes.theme_key"), nullable=True)
    overall_score = Column(Numeric(5, 2), nullable=False)
    risk_level = Column(String(20), nullable=False)
    week_delta = Column(Numeric(5, 2), nullable=True)
