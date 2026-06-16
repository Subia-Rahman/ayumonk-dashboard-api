from __future__ import annotations
"""Read/write services for the wellness endpoints (Phase 3).

  * WellnessIndexService — backs ``GET /api/v1/wellness/index``. Lookup
    against ``theme_submission_scores`` with **self-heal**: if no row
    exists for the caller, attempts to backfill from their most recent
    ``employee_form_response`` (covers users who submitted forms before
    the Phase-3 write hook was deployed — the hook now runs on every
    new submission, but back-dated rows need to be processed on first
    read).

  * WellnessMoodService — backs ``POST /api/v1/wellness/mood`` +
    ``GET /api/v1/wellness/mood/today``. Inserts and queries against
    ``user_mood_log``. The /today endpoint replaces the frontend's
    localStorage "did I log mood today?" hack so per-user state can't
    leak across users sharing a browser.
"""

import logging
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.employee_form_response import EmployeeFormResponse
from config_service.app.models.theme_submission_score import ThemeSubmissionScore
from config_service.app.models.user_mood_log import UserMoodLog


_logger = logging.getLogger(__name__)


class WellnessIndexService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_latest_for_email(self, email: str) -> ThemeSubmissionScore:
        """Return the most recent ``theme_submission_scores`` row for
        the given employee email.

        Self-heal path: when no persisted row exists but the user DOES
        have at least one ``employee_form_response``, run the Phase-3
        persist logic on the latest response (idempotent on response_id
        via UNIQUE constraint) and re-query. Covers the deployment
        seam — forms submitted before the write hook shipped don't
        have a WI row until first read.

        Raises 404 when the user has never submitted a scorable form,
        OR when the latest submission has no scorable answers (no
        KPI-mapped questions). Both cases are correct empty-states for
        the UI donut."""
        row = await self._lookup_latest(email)
        if row is not None:
            return row

        # Self-heal — try to backfill from the latest existing response.
        healed = await self._backfill_from_latest_response(email)
        if healed is not None:
            return healed

        raise BusinessException(
            message=(
                "No wellness submissions found for this user — "
                "submit a wellness form first."
            ),
            status_code=404,
        )

    async def _lookup_latest(self, email: str) -> Optional[ThemeSubmissionScore]:
        stmt = (
            select(ThemeSubmissionScore)
            .where(
                ThemeSubmissionScore.employee_email == email,
                ThemeSubmissionScore.is_deleted == False,  # noqa: E712
            )
            .order_by(ThemeSubmissionScore.created_at.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _backfill_from_latest_response(
        self, email: str
    ) -> Optional[ThemeSubmissionScore]:
        """Find the user's most recent form response, run the Phase-3
        WI persist on it, and return the resulting row.

        Returns None when the user has no submissions at all (404 is
        the right answer) OR when the latest submission produced no
        scorable rows (e.g. session had only free-text questions, or
        the kpi_questions catalog has been cleaned up since)."""
        response_stmt = (
            select(
                EmployeeFormResponse.response_id,
                EmployeeFormResponse.company_id,
            )
            .where(
                EmployeeFormResponse.employee_email == email,
                EmployeeFormResponse.is_deleted == False,  # noqa: E712
            )
            .order_by(EmployeeFormResponse.submitted_at.desc())
            .limit(1)
        )
        latest = (await self.db.execute(response_stmt)).first()
        if latest is None:
            return None

        # Lazy import to avoid a circular dep (wellness_scoring imports
        # from this module's neighbour wellness package).
        from config_service.app.services.wellness_scoring import (
            WellnessScoringService,
        )

        try:
            persisted = await WellnessScoringService(self.db).persist_for_response(
                response_id=latest.response_id,
                employee_email=email,
                company_id=latest.company_id,
            )
        except Exception:
            # Self-heal failure mustn't break the request — log and
            # fall through to the 404 path so the user gets a clean
            # empty-state instead of a 500.
            _logger.exception(
                "WELLNESS_INDEX_SELF_HEAL_FAILED | email=%s | response_id=%s",
                email, latest.response_id,
            )
            return None

        if persisted is not None:
            _logger.info(
                "WELLNESS_INDEX_SELF_HEAL | email=%s | response_id=%s",
                email, latest.response_id,
            )
        return persisted


class WellnessMoodService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_today_for_email(self, email: str) -> Optional[UserMoodLog]:
        """Return today's most-recent mood entry for the user, or None
        if they haven't logged yet today. Used by
        ``GET /api/v1/wellness/mood/today`` to drive the "Logged for
        today ✓" UI lock server-side (replaces the frontend's
        localStorage which leaks between users on a shared browser)."""
        today = date.today()
        stmt = (
            select(UserMoodLog)
            .where(
                UserMoodLog.employee_email == email,
                UserMoodLog.is_deleted == False,  # noqa: E712
                func.date(UserMoodLog.logged_at) == today,
            )
            .order_by(UserMoodLog.logged_at.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def submit(
        self,
        *,
        email: str,
        score: int,
        company_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        actor_user_id: Optional[int] = None,
    ) -> UserMoodLog:
        """Persist a mood-log row. ``user_id`` is the company_users.id
        when known (matches the FK); ``actor_user_id`` is the integer
        auth-service id used by ``AuditMixin.created_by``."""
        row = UserMoodLog(
            employee_email=email,
            score=score,
            company_id=company_id,
            user_id=user_id,
            logged_at=datetime.utcnow(),
            created_by=actor_user_id,
            updated_by=actor_user_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row
