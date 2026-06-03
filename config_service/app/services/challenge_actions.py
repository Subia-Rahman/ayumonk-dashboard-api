from datetime import datetime, timedelta

from sqlalchemy import distinct, func, or_, select

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.badge_master import BadgeMaster
from config_service.app.models.kpi_challenge import KPIChallenge
from config_service.app.models.user_badge import UserBadge
from config_service.app.models.user_challenge_completion import UserChallengeCompletion
from config_service.app.models.user_streak import UserStreak
from config_service.app.models.user_xp import UserXp
from config_service.app.repositories.challenge import ChallengeRepository
from config_service.app.repositories.company_users import UserRepository as CompanyUserRepository
from config_service.app.repositories.kpi_challenge import KPIChallengeRepository
from config_service.app.repositories.user_challenge_completions import UserChallengeCompletionRepository
from config_service.app.schemas.challenge_actions import (
    BadgeInfo,
    ChallengeActionRequest,
    ChallengeActionResponse,
    DashboardChallengeStatus,
    DashboardChallengesResponse,
    StreakInfo,
    XpInfo,
)


# Level thresholds: (min_total_xp, level, label). Ordered descending so the
# first match wins.
_LEVEL_THRESHOLDS = (
    (2000, 6, "Banyan Legend"),
    (1000, 5, "Banyan Tree"),
    (600,  4, "Banyan Sapling"),
    (300,  3, "Tree"),
    (100,  2, "Sapling"),
    (0,    1, "Seedling"),
)

_STREAK_ELIGIBLE_TYPES = {"counter", "toggle", "choice", "multi", "timer"}


class ChallengeActionService:
    def __init__(self, db):
        self.db = db
        self.challenge_repo = ChallengeRepository(db)
        self.company_user_repo = CompanyUserRepository(db)
        self.kpi_challenge_repo = KPIChallengeRepository(db)
        self.completion_repo = UserChallengeCompletionRepository(db)

    async def mark_challenge_done(
        self,
        *,
        user_id: int,
        user_email: str,
        payload: ChallengeActionRequest,
    ) -> ChallengeActionResponse:
        company_user = await self.company_user_repo.get_by_email(user_email)
        if not company_user:
            raise BusinessException(message="Company not found for user", status_code=403)

        challenge = await self.challenge_repo.get_by_id(payload.challenge_id)
        if not challenge:
            raise BusinessException(message="Challenge not found", status_code=404)

        today = datetime.utcnow().date()

        # B — KPI window guard. Reject completions for challenges that have no
        # active kpi_challenges row covering today (regardless of company, per
        # the product requirement).
        if not await self._challenge_in_active_window(payload.challenge_id, today):
            raise BusinessException(
                message="This challenge is not active today",
                status_code=400,
            )

        challenge_type = (challenge.challenge_type or "").lower()
        is_counter = challenge_type == "counter"
        is_rating = challenge_type == "rating"
        is_streak_eligible = challenge_type in _STREAK_ELIGIBLE_TYPES

        value_logged = self._normalize_value(challenge.challenge_type, payload)
        target = challenge.target_value

        existing = await self.completion_repo.get_by_user_challenge_date(
            user_id=user_id,
            challenge_id=payload.challenge_id,
            completion_date=today,
        )

        # --- Counter same-day accumulation path -------------------------------
        # Preserves the original UX: multiple submissions roll up into the same
        # completion row until target is met. Streak/badge are not awarded on
        # accumulation — only on the first completion of the day.
        if existing and is_counter and target is not None:
            if (existing.value_logged or 0) >= target:
                raise BusinessException(message="Already completed today", status_code=409)

            new_total = (existing.value_logged or 0) + (value_logged or 0)
            new_xp, status = self._compute_xp_and_status(
                challenge_type=challenge.challenge_type,
                target=target,
                value=new_total,
                full_xp=challenge.xp_reward,
            )
            delta_xp = max(0, new_xp - (existing.xp_earned or 0))

            existing.value_logged = new_total
            existing.xp_earned = new_xp
            self.db.add(existing)
            await self.db.flush()

            xp_state = await self._update_user_xp(user_id, delta_xp)

            # Counter accumulation: streak + KPI-completion already counted
            # on the first submission of the day. Level badges can still fire
            # if a partial submission pushes the user across a level threshold.
            badge_earned, badge_info = await self._award_badges(
                user_id=user_id,
                challenge_id=payload.challenge_id,
                current_streak=None,
                new_level=xp_state["current_level"] if xp_state["level_up"] else None,
                count_kpi_completion=False,
            )

            await self.db.commit()

            return ChallengeActionResponse(
                message=(
                    "Challenge marked as completed"
                    if status == "done"
                    else "Progress logged"
                ),
                xp_earned=existing.xp_earned,
                status=status,
                completion_date=today,
                value_logged=existing.value_logged,
                streak=None,
                xp=XpInfo(**xp_state),
                badge_earned=badge_earned,
                badge=BadgeInfo(**badge_info) if badge_info else None,
            )

        if existing:
            raise BusinessException(message="Already completed today", status_code=409)

        # --- Fresh completion path -------------------------------------------
        xp_earned, status = self._compute_xp_and_status(
            challenge_type=challenge.challenge_type,
            target=target,
            value=value_logged,
            full_xp=challenge.xp_reward,
        )

        completion = UserChallengeCompletion(
            user_id=user_id,
            challenge_id=payload.challenge_id,
            company_id=company_user.company_id,
            completion_date=today,
            value_logged=value_logged,
            xp_earned=xp_earned,
        )
        self.db.add(completion)
        await self.db.flush()

        # E — Streak upsert (only for streak-eligible types AND only if the
        # user actually engaged — skipped completions don't count toward streak).
        streak_result = None
        if is_streak_eligible and status != "skipped":
            streak_result = await self._upsert_streak(
                user_id=user_id,
                challenge_id=payload.challenge_id,
                today=today,
            )

        # F — XP aggregate update (always, including for rating type).
        xp_state = await self._update_user_xp(user_id, xp_earned)

        # G — Badge check. Three trigger types fire here:
        #   * streak — only for streak-eligible types that just advanced
        #   * kpi_completions — for any non-skipped completion (rating counts:
        #     mood-logging still represents engagement with that KPI)
        #   * level — whenever XP just pushed the user up a level
        badge_earned, badge_info = await self._award_badges(
            user_id=user_id,
            challenge_id=payload.challenge_id,
            current_streak=streak_result["current_streak"] if streak_result else None,
            new_level=xp_state["current_level"] if xp_state["level_up"] else None,
            count_kpi_completion=(status != "skipped"),
        )

        await self.db.commit()

        return ChallengeActionResponse(
            message=(
                "Challenge marked as completed"
                if status == "done"
                else "Progress logged"
            ),
            xp_earned=xp_earned,
            status=status,
            completion_date=today,
            value_logged=value_logged,
            streak=StreakInfo(**streak_result) if streak_result else None,
            xp=XpInfo(**xp_state),
            badge_earned=badge_earned,
            badge=BadgeInfo(**badge_info) if badge_info else None,
        )

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    async def _challenge_in_active_window(self, challenge_id, today) -> bool:
        stmt = (
            select(KPIChallenge.id)
            .where(
                KPIChallenge.challenge_key == challenge_id,
                KPIChallenge.is_deleted == False,  # noqa: E712
                KPIChallenge.is_active == True,    # noqa: E712
                KPIChallenge.start_date <= today,
                or_(KPIChallenge.end_date.is_(None), KPIChallenge.end_date >= today),
            )
            .limit(1)
        )
        res = await self.db.execute(stmt)
        return res.first() is not None

    async def _upsert_streak(self, *, user_id, challenge_id, today) -> dict:
        stmt = select(UserStreak).where(
            UserStreak.user_id == user_id,
            UserStreak.challenge_id == challenge_id,
        )
        res = await self.db.execute(stmt)
        row = res.scalar_one_or_none()

        yesterday = today - timedelta(days=1)

        if row is None:
            new_row = UserStreak(
                user_id=user_id,
                challenge_id=challenge_id,
                current_streak=1,
                longest_streak=1,
                last_completion_date=today,
            )
            self.db.add(new_row)
            await self.db.flush()
            return {
                "current_streak": 1,
                "longest_streak": 1,
                "last_completion_date": today,
                "streak_status": "new",
            }

        if row.last_completion_date == today:
            # Defensive: caller should have caught the duplicate by now.
            return {
                "current_streak": row.current_streak,
                "longest_streak": row.longest_streak,
                "last_completion_date": row.last_completion_date,
                "streak_status": "already_done",
            }

        if row.last_completion_date == yesterday:
            new_current = (row.current_streak or 0) + 1
            row.current_streak = new_current
            row.longest_streak = max(row.longest_streak or 0, new_current)
            streak_status = "incremented"
        else:
            row.current_streak = 1
            # longest_streak never decreases
            streak_status = "reset"

        row.last_completion_date = today
        row.updated_at = datetime.utcnow()
        self.db.add(row)
        await self.db.flush()

        return {
            "current_streak": row.current_streak,
            "longest_streak": row.longest_streak,
            "last_completion_date": row.last_completion_date,
            "streak_status": streak_status,
        }

    async def _update_user_xp(self, user_id: int, xp_delta: int) -> dict:
        stmt = select(UserXp).where(UserXp.user_id == user_id)
        res = await self.db.execute(stmt)
        row = res.scalar_one_or_none()

        if row is None:
            level, label = self._compute_level(xp_delta)
            row = UserXp(
                user_id=user_id,
                total_xp=xp_delta,
                xp_this_week=xp_delta,
                current_level=level,
                level_label=label,
            )
            self.db.add(row)
            await self.db.flush()
            return {
                "xp_earned_now": xp_delta,
                "total_xp": row.total_xp,
                "xp_this_week": row.xp_this_week,
                "current_level": row.current_level,
                "level_label": row.level_label,
                "level_up": level > 1,
            }

        old_level = row.current_level or 1
        row.total_xp = (row.total_xp or 0) + xp_delta
        row.xp_this_week = (row.xp_this_week or 0) + xp_delta

        new_level, new_label = self._compute_level(row.total_xp)
        level_up = new_level > old_level
        if level_up:
            row.current_level = new_level
            row.level_label = new_label

        row.updated_at = datetime.utcnow()
        self.db.add(row)
        await self.db.flush()

        return {
            "xp_earned_now": xp_delta,
            "total_xp": row.total_xp,
            "xp_this_week": row.xp_this_week,
            "current_level": row.current_level,
            "level_label": row.level_label,
            "level_up": level_up,
        }

    async def _award_badges(
        self,
        *,
        user_id: int,
        challenge_id,
        current_streak: int | None,
        new_level: int | None,
        count_kpi_completion: bool,
    ) -> tuple[bool, dict | None]:
        """
        Evaluate all badge trigger types for this completion and insert any
        newly-earned user_badges rows. Returns (earned_any, headline_badge)
        where headline_badge is the highest-trigger_value award (most realistic
        UX: a single completion almost never hits two milestones at once, but
        if it does we surface the bigger one).
        """
        kpi_key = await self._kpi_for_challenge(challenge_id)
        awarded: list[tuple[int, dict]] = []

        # --- streak ----------------------------------------------------------
        if current_streak and current_streak > 0:
            stmt = select(BadgeMaster).where(
                BadgeMaster.trigger_type == "streak",
                BadgeMaster.trigger_value == current_streak,
                or_(BadgeMaster.kpi_key.is_(None), BadgeMaster.kpi_key == kpi_key),
                BadgeMaster.is_active == True,     # noqa: E712
                BadgeMaster.is_deleted == False,   # noqa: E712
            )
            for badge in (await self.db.execute(stmt)).scalars().all():
                if await self._award_if_new(user_id, badge):
                    awarded.append((badge.trigger_value, self._badge_dict(badge)))

        # --- kpi_completions -------------------------------------------------
        if count_kpi_completion and kpi_key is not None:
            kpi_count = await self._count_user_completions_in_kpi(user_id, kpi_key)
            stmt = select(BadgeMaster).where(
                BadgeMaster.trigger_type == "kpi_completions",
                BadgeMaster.kpi_key == kpi_key,
                BadgeMaster.trigger_value <= kpi_count,
                BadgeMaster.is_active == True,     # noqa: E712
                BadgeMaster.is_deleted == False,   # noqa: E712
            )
            for badge in (await self.db.execute(stmt)).scalars().all():
                if await self._award_if_new(user_id, badge):
                    awarded.append((badge.trigger_value, self._badge_dict(badge)))

        # --- level -----------------------------------------------------------
        if new_level is not None:
            stmt = select(BadgeMaster).where(
                BadgeMaster.trigger_type == "level",
                BadgeMaster.trigger_value <= new_level,
                BadgeMaster.kpi_key.is_(None),
                BadgeMaster.is_active == True,     # noqa: E712
                BadgeMaster.is_deleted == False,   # noqa: E712
            )
            for badge in (await self.db.execute(stmt)).scalars().all():
                if await self._award_if_new(user_id, badge):
                    awarded.append((badge.trigger_value, self._badge_dict(badge)))

        if not awarded:
            return False, None
        return True, max(awarded, key=lambda x: x[0])[1]

    async def _award_if_new(self, user_id: int, badge: BadgeMaster) -> bool:
        existing = await self.db.execute(
            select(UserBadge.id).where(
                UserBadge.user_id == user_id,
                UserBadge.badge_id == badge.id,
            )
        )
        if existing.first() is not None:
            return False
        self.db.add(UserBadge(user_id=user_id, badge_id=badge.id))
        await self.db.flush()
        return True

    @staticmethod
    def _badge_dict(badge: BadgeMaster) -> dict:
        return {
            "badge_key": badge.badge_key,
            "label": badge.label,
            "icon": badge.icon,
            "level": badge.level,
        }

    async def _kpi_for_challenge(self, challenge_id):
        """Resolve the KPI of the active kpi_challenges mapping for this
        challenge today. Returns None if no active mapping exists (e.g. the
        caller already checked the window guard so this is just a re-read)."""
        today = datetime.utcnow().date()
        stmt = (
            select(KPIChallenge.kpi_key)
            .where(
                KPIChallenge.challenge_key == challenge_id,
                KPIChallenge.is_deleted == False,  # noqa: E712
                KPIChallenge.is_active == True,    # noqa: E712
                KPIChallenge.start_date <= today,
                or_(KPIChallenge.end_date.is_(None), KPIChallenge.end_date >= today),
            )
            .limit(1)
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def _count_user_completions_in_kpi(self, user_id: int, kpi_key) -> int:
        """Count distinct completion rows for this user across all challenges
        currently or previously mapped to the given KPI. A challenge mapped to
        multiple KPIs counts once per (user, kpi) — distinct on completion.id
        avoids double-counting if the kpi_challenges join multiplies rows."""
        stmt = (
            select(func.count(distinct(UserChallengeCompletion.id)))
            .select_from(UserChallengeCompletion)
            .join(
                KPIChallenge,
                KPIChallenge.challenge_key == UserChallengeCompletion.challenge_id,
            )
            .where(
                UserChallengeCompletion.user_id == user_id,
                UserChallengeCompletion.is_deleted == False,  # noqa: E712
                KPIChallenge.kpi_key == kpi_key,
                KPIChallenge.is_deleted == False,  # noqa: E712
            )
        )
        res = await self.db.execute(stmt)
        return res.scalar_one() or 0

    @staticmethod
    def _compute_level(total_xp: int) -> tuple[int, str]:
        total_xp = max(0, total_xp or 0)
        for threshold, level, label in _LEVEL_THRESHOLDS:
            if total_xp >= threshold:
                return level, label
        return 1, "Seedling"

    # -------------------------------------------------------------------------
    # Dashboard listing (unchanged from original implementation)
    # -------------------------------------------------------------------------

    async def get_dashboard_challenges(
        self,
        *,
        user_id: int,
        user_email: str,
    ) -> DashboardChallengesResponse:
        company_user = await self.company_user_repo.get_by_email(user_email)
        if not company_user:
            raise BusinessException(message="Company not found for user", status_code=403)

        today = datetime.utcnow().date()
        rows = await self.kpi_challenge_repo.list_active_by_date(today)
        completions = await self.completion_repo.list_by_user_date(user_id, today)
        completion_map = {c.challenge_id: c for c in completions}

        challenges: list[DashboardChallengeStatus] = []
        for mapping, challenge in rows:
            completion = completion_map.get(challenge.challenge_key)
            if completion:
                status = self._status_from_completion(
                    target=challenge.target_value,
                    value=completion.value_logged,
                )
                challenges.append(
                    DashboardChallengeStatus(
                        challenge_id=challenge.challenge_key,
                        title=challenge.name,
                        kpi_key=mapping.kpi_key,
                        status=status,
                        value_logged=completion.value_logged,
                        xp_earned=completion.xp_earned,
                    )
                )
            else:
                challenges.append(
                    DashboardChallengeStatus(
                        challenge_id=challenge.challenge_key,
                        title=challenge.name,
                        kpi_key=mapping.kpi_key,
                        status="pending",
                        value_logged=None,
                        xp_earned=None,
                    )
                )

        return DashboardChallengesResponse(challenges=challenges)

    @staticmethod
    def _compute_xp_and_status(*, challenge_type: str | None, target, value, full_xp: int) -> tuple[int, str]:
        ctype = (challenge_type or "").lower()
        if value is None:
            return 0, "skipped"

        if ctype == "toggle":
            return (full_xp, "done") if value > 0 else (0, "skipped")

        if target is None:
            return full_xp, "done"

        if value >= target:
            return full_xp, "done"
        ratio = max(0, min(1, value / target))
        return int(round(full_xp * ratio)), "partial"

    @staticmethod
    def _status_from_completion(*, target, value) -> str:
        if target is None:
            return "done"
        if value is None:
            return "skipped"
        return "done" if value >= target else "partial"

    @staticmethod
    def _normalize_value(challenge_type: str | None, payload: ChallengeActionRequest) -> int | None:
        ctype = (challenge_type or "").lower()
        # Counter taps are server-controlled at +1 per call. Any value_logged
        # in the request is ignored so a client that sends a cumulative tap
        # count (or any other value) cannot over-complete the challenge.
        # First tap stores 1; subsequent taps in the same day add 1 each via
        # the counter-accumulation branch in mark_challenge_done.
        if ctype == "counter":
            return 1
        if ctype in ("timer", "rating"):
            if ctype == "timer" and payload.timer_seconds is not None:
                return payload.timer_seconds
            if ctype == "rating" and payload.rating_value is not None:
                return payload.rating_value
            if payload.value_logged is not None:
                return payload.value_logged
            raise BusinessException(message="value_logged is required for this challenge type", status_code=422)

        if ctype == "toggle":
            if payload.toggle_value is None:
                raise BusinessException(message="toggle_value is required for toggle challenges", status_code=422)
            return 1 if payload.toggle_value else 0

        if ctype == "choice":
            if payload.choice_value is None:
                raise BusinessException(message="choice_value is required for choice challenges", status_code=422)
            return payload.choice_value

        if ctype == "multi":
            if payload.multi_values is None:
                raise BusinessException(message="multi_values are required for multi challenges", status_code=422)
            return len(payload.multi_values)

        # Fallback to value_logged if type is unknown
        return payload.value_logged
