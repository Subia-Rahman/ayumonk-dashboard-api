"""Per-type eligibility checks for the reminder dispatcher (Phases 6 & 6.5).

The dispatcher today fires every enabled reminder toggle for any user
whose ``reminder_time`` matches the current minute. That over-fires —
``program_ending`` shouldn't ping someone whose company has no programs
near their end date, ``daily_challenge`` shouldn't ping someone who's
already completed everything for today, etc. This module narrows the
firings to the spec's semantics:

Company-level checks (Phase 6 — no auth-user mapping needed):
  * ``program_ending``  → ``company_has_program_ending_soon``
  * ``new_program``     → ``company_has_new_program_opening_soon``

User-level checks (Phase 6.5 — bridge UUID→Integer via email):
  * ``daily_challenge`` → ``user_has_incomplete_challenges_today``
  * ``streak_alert``    → ``user_streak_at_risk``

The user-level checks need to bridge ``company_users.id`` (UUID, what the
dispatcher loop has) → auth-service ``users.id`` (Integer, what
``user_challenge_completion`` and ``user_streak`` use). We resolve the
bridge per-dispatch via email (``resolve_auth_user_id_by_email``);
no schema change required.

All check functions return a bool. Callers that need richer detail
(e.g. "WHICH challenge is about to end?") should query the repo
directly; these checks answer the binary "should I fire?".
"""

from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.models.user import User as AuthUser
from config_service.app.models.kpi_challenge import KPIChallenge
from config_service.app.models.user_challenge_completion import (
    UserChallengeCompletion,
)
from config_service.app.models.user_streak import UserStreak


# Window-closing reminder fires when at least one of the company's
# active programs ends within this many days. Spec §7b cites 3 days as
# the canonical "ending soon" trigger; we use a 1-7 day window so the
# UI also catches windows that close in the next few days (users want a
# heads-up earlier than spec-strict-3).
PROGRAM_ENDING_LOOKAHEAD_DAYS = 7

# Window-opening reminder fires when at least one of the company's
# programs starts within this many days. Spec §7b cites 1 day ("new
# program tomorrow"); we use a 1-3 day window so the message lands
# slightly earlier and survives users who don't check daily.
NEW_PROGRAM_LOOKAHEAD_DAYS = 3


async def company_has_program_ending_soon(
    session: AsyncSession,
    *,
    company_id: Optional[UUID],
    today: Optional[date] = None,
    lookahead_days: int = PROGRAM_ENDING_LOOKAHEAD_DAYS,
) -> bool:
    """True when the company has at least one active kpi_challenge whose
    ``end_date`` falls within ``[today, today + lookahead_days]``.

    NULL ``end_date`` is open-ended and never triggers the reminder
    (there's nothing to close). Soft-deleted / paused rows are skipped."""
    if company_id is None:
        # Cross-tenant / unassigned users can't have a "program ending".
        return False
    today = today or date.today()
    threshold = today + timedelta(days=lookahead_days)
    stmt = (
        select(KPIChallenge.id)
        .where(
            KPIChallenge.company_id == company_id,
            KPIChallenge.is_deleted == False,  # noqa: E712
            KPIChallenge.is_active == True,  # noqa: E712
            KPIChallenge.end_date.is_not(None),
            KPIChallenge.end_date >= today,
            KPIChallenge.end_date <= threshold,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def company_has_new_program_opening_soon(
    session: AsyncSession,
    *,
    company_id: Optional[UUID],
    today: Optional[date] = None,
    lookahead_days: int = NEW_PROGRAM_LOOKAHEAD_DAYS,
) -> bool:
    """True when the company has at least one kpi_challenge whose
    ``start_date`` falls within ``[today + 1, today + lookahead_days]``.

    Excludes programs starting today (those are already-active, no
    "tomorrow" framing applies). Soft-deleted / paused rows are
    skipped."""
    if company_id is None:
        return False
    today = today or date.today()
    earliest = today + timedelta(days=1)
    latest = today + timedelta(days=lookahead_days)
    stmt = (
        select(KPIChallenge.id)
        .where(
            KPIChallenge.company_id == company_id,
            KPIChallenge.is_deleted == False,  # noqa: E712
            KPIChallenge.is_active == True,  # noqa: E712
            KPIChallenge.start_date >= earliest,
            KPIChallenge.start_date <= latest,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Phase 6.5 — user-level eligibility
# ---------------------------------------------------------------------------

# Streak length at and above which we consider it "worth alerting" the user
# they're about to break it. Spec §7 quotes 3 days as the typical floor —
# below 3 the user isn't yet invested enough for the alert to be useful.
STREAK_AT_RISK_THRESHOLD = 3


async def resolve_auth_user_id_by_email(
    session: AsyncSession, *, email: str
) -> Optional[int]:
    """Translate a ``company_users.email`` into the auth-service
    ``users.id`` (Integer) needed to query ``user_challenge_completion``
    and ``user_streak``.

    Returns None when no auth row exists for that email — the dispatcher
    falls back to the conservative "skip user-level eligibility checks"
    path so an unlinked user's reminders neither over-fire nor
    silently disappear; they just don't get the user-level narrowing.
    """
    if not email:
        return None
    stmt = (
        select(AuthUser.id)
        .where(AuthUser.email == email)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def user_has_incomplete_challenges_today(
    session: AsyncSession,
    *,
    auth_user_id: int,
    company_id: Optional[UUID],
    today: Optional[date] = None,
) -> bool:
    """True when the user has at least one active challenge today that
    they have NOT yet completed.

    "Active today" = the ``kpi_challenges`` window covers today
    (``start_date <= today`` AND (``end_date IS NULL`` OR
    ``end_date >= today``)) AND ``is_active = TRUE``,
    ``is_deleted = FALSE``.

    "Not yet completed" = no row in ``user_challenge_completion`` with
    matching ``(user_id, challenge_id, completion_date=today)``.

    Returns False when the user is fully caught up (no reminder needed)
    or when ``company_id`` is missing.
    """
    if company_id is None:
        # Cross-tenant / unassigned users — no active challenges to chase.
        return False
    today = today or date.today()
    # NOT EXISTS subquery: one SQL pass, stops at the first uncompleted
    # active challenge. Uses kpi_challenges.challenge_key == ucc.challenge_id
    # to match the FK relationship (both reference challenges.challenge_key).
    completion_subq = (
        select(UserChallengeCompletion.id)
        .where(
            UserChallengeCompletion.user_id == auth_user_id,
            UserChallengeCompletion.challenge_id == KPIChallenge.challenge_key,
            UserChallengeCompletion.completion_date == today,
        )
    )
    stmt = (
        select(KPIChallenge.id)
        .where(
            KPIChallenge.company_id == company_id,
            KPIChallenge.is_deleted == False,  # noqa: E712
            KPIChallenge.is_active == True,  # noqa: E712
            KPIChallenge.start_date <= today,
            (
                KPIChallenge.end_date.is_(None)
                | (KPIChallenge.end_date >= today)
            ),
            ~completion_subq.exists(),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def user_streak_at_risk(
    session: AsyncSession,
    *,
    auth_user_id: int,
    today: Optional[date] = None,
    threshold: int = STREAK_AT_RISK_THRESHOLD,
) -> bool:
    """True when the user has at least one streak that's
    ``threshold``-or-longer AND hasn't been touched yet today.

    Logic: ``current_streak >= threshold`` AND
    (``last_completion_date IS NULL`` OR ``last_completion_date <
    today``). The NULL branch handles the edge case where a row was
    created without ever being incremented; in practice
    ``last_completion_date`` is set whenever a streak ticks up.

    Returns False when the user has no streaks at risk or no streak
    rows at all (new users with current_streak=0 don't get pinged).
    """
    today = today or date.today()
    stmt = (
        select(UserStreak.id)
        .where(
            UserStreak.user_id == auth_user_id,
            UserStreak.current_streak >= threshold,
            (
                UserStreak.last_completion_date.is_(None)
                | (UserStreak.last_completion_date < today)
            ),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None
