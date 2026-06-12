"""Read/write services for the user-facing suggestions endpoints (Phase 4).

  * UserSuggestionsService.get_my_latest — backs ``GET /suggestions/my``.
    Returns the engine output from the user's most recent submission
    (joined with the ``suggestions`` content so the UI has a complete
    card payload in one round-trip).

  * UserSuggestionsService.record_action — backs
    ``POST /suggestions/{log_id}/action``. Updates the action +
    actioned_at on a single log row, with an authorization guard so a
    user can only action their own rows.
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.employee_form_response import EmployeeFormResponse
from config_service.app.models.suggestion import Suggestion
from config_service.app.models.user_suggestion_log import UserSuggestionLog


_logger = logging.getLogger(__name__)


# Action values allowed by the DB CHECK constraint on user_suggestion_log
# .action. Kept in sync with schemas.user_suggestions.SuggestionAction
# and the migration SQL.
_VALID_ACTIONS = {"done", "skipped", "saved"}


class UserSuggestionsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_my_latest(self, email: str) -> dict:
        """Return ``{response_id, submitted_at, items}`` for the user's
        most recent submission that has engine output.

        Self-heal path: when no ``user_suggestion_log`` row exists for
        the user, attempts to backfill from their most recent
        ``employee_form_response`` (idempotent — the engine's
        ``UNIQUE (response_id, suggestion_id)`` constraint guarantees
        re-runs are safe). Covers the deployment seam where forms
        submitted before Phase 4 have no engine output yet.

        Falls back to "no submissions" (404 from the route) when the
        user has never had a form submission, OR when the latest
        submission produced no suggestions (all KPIs are in the 'good'
        band, or no mappings exist for at-risk KPIs).
        """
        # 1. Most recent log row → tells us which response_id to bundle.
        latest_response_id = await self._lookup_latest_response_id(email)

        if latest_response_id is None:
            # Self-heal — try to backfill from the latest existing
            # form response before declaring 404.
            latest_response_id = await self._backfill_from_latest_response(
                email
            )

        if latest_response_id is None:
            raise BusinessException(
                message=(
                    "No suggestions available yet — submit a wellness form "
                    "first so the engine can pick lifestyle recommendations."
                ),
                status_code=404,
            )

        # 2. Pull every log row + joined Suggestion content for that
        #    response. Ordered by priority asc for stable UI render.
        stmt = (
            select(UserSuggestionLog, Suggestion)
            .join(Suggestion, Suggestion.id == UserSuggestionLog.suggestion_id)
            .where(
                UserSuggestionLog.response_id == latest_response_id,
                UserSuggestionLog.is_deleted == False,  # noqa: E712
            )
            .order_by(
                UserSuggestionLog.priority.asc(),
                UserSuggestionLog.shown_at.asc(),
            )
        )
        rows = (await self.db.execute(stmt)).all()

        # 3. Resolve the parent submission's submitted_at so the response
        #    envelope can mirror /wellness/index's shape.
        submitted_at_stmt = select(EmployeeFormResponse.submitted_at).where(
            EmployeeFormResponse.response_id == latest_response_id
        )
        submitted_at = (
            await self.db.execute(submitted_at_stmt)
        ).scalar_one_or_none() or datetime.utcnow()

        items: list[dict] = []
        for log_row, suggestion in rows:
            items.append(
                {
                    "log_id": log_row.id,
                    "response_id": log_row.response_id,
                    "kpi_key": log_row.kpi_key,
                    "trigger_mode": log_row.trigger_mode,
                    "priority": log_row.priority,
                    "shown_at": log_row.shown_at,
                    "action": log_row.action,
                    "actioned_at": log_row.actioned_at,
                    "suggestion_id": suggestion.id,
                    "suggestion_type": suggestion.suggestion_type,
                    "title": suggestion.title,
                    "description": suggestion.description,
                    "url": suggestion.url,
                    "dosha_type": suggestion.dosha_type,
                    "difficulty": suggestion.difficulty,
                    "duration_mins": suggestion.duration_mins,
                }
            )

        return {
            "response_id": latest_response_id,
            "submitted_at": submitted_at,
            "items": items,
        }

    async def _lookup_latest_response_id(self, email: str) -> Optional[str]:
        """Return the user's most-recent ``user_suggestion_log.response_id``,
        or None when they have no log rows yet."""
        stmt = (
            select(UserSuggestionLog.response_id)
            .where(
                UserSuggestionLog.employee_email == email,
                UserSuggestionLog.is_deleted == False,  # noqa: E712
            )
            .order_by(UserSuggestionLog.shown_at.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _backfill_from_latest_response(
        self, email: str
    ) -> Optional[str]:
        """Find the user's most-recent ``employee_form_response``, run
        the Phase-4 suggestion engine on it, and return the
        ``response_id`` when at least one log row was produced.

        Returns None when the user has no submissions, OR when the
        engine produced no picks (all KPIs in 'good' band / no
        mappings configured / dosha filter dropped everything)."""
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

        # Lazy import — suggestion_engine and this module are siblings;
        # keep the dependency one-way from engine→log to mirror the
        # write-path direction.
        from config_service.app.services.suggestion_engine import (
            SuggestionEngineService,
        )

        try:
            rows = await SuggestionEngineService(self.db).compute_and_persist(
                response_id=latest.response_id,
                employee_email=email,
                company_id=latest.company_id,
            )
        except Exception:
            _logger.exception(
                "USER_SUGGESTIONS_SELF_HEAL_FAILED | email=%s | response_id=%s",
                email, latest.response_id,
            )
            return None

        if not rows:
            # Engine produced nothing — empty state. Don't claim a
            # response_id we can't return data for.
            return None

        _logger.info(
            "USER_SUGGESTIONS_SELF_HEAL | email=%s | response_id=%s | rows=%s",
            email, latest.response_id, len(rows),
        )
        return latest.response_id

    async def record_action(
        self,
        *,
        log_id: UUID,
        email: str,
        action: str,
        actor_user_id: Optional[int] = None,
    ) -> UserSuggestionLog:
        """Set ``action`` + ``actioned_at`` on a single log row.

        Authorization: the row must belong to ``email`` (server-side
        check; not relying on the client to send the right id). Returns
        404 when the row doesn't exist OR isn't owned by the caller —
        same surface either way so we don't leak existence of other
        users' rows.
        """
        normalized = (action or "").strip().lower()
        if normalized not in _VALID_ACTIONS:
            raise BusinessException(
                message=(
                    f"Invalid action '{action}'. "
                    f"Allowed: {', '.join(sorted(_VALID_ACTIONS))}."
                ),
                status_code=422,
            )

        stmt = select(UserSuggestionLog).where(
            UserSuggestionLog.id == log_id,
            UserSuggestionLog.employee_email == email,
            UserSuggestionLog.is_deleted == False,  # noqa: E712
        )
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise BusinessException(
                message="Suggestion log entry not found",
                status_code=404,
            )

        row.action = normalized
        row.actioned_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
        if actor_user_id is not None:
            row.updated_by = actor_user_id
        await self.db.commit()
        await self.db.refresh(row)
        return row
