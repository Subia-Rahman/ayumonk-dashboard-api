from datetime import datetime

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.user_challenge_completion import UserChallengeCompletion
from config_service.app.repositories.challenge import ChallengeRepository
from config_service.app.repositories.company_users import UserRepository as CompanyUserRepository
from config_service.app.repositories.kpi_challenge import KPIChallengeRepository
from config_service.app.repositories.user_challenge_completions import UserChallengeCompletionRepository
from config_service.app.schemas.challenge_actions import (
    ChallengeActionRequest,
    ChallengeActionResponse,
    DashboardChallengeStatus,
    DashboardChallengesResponse,
)


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

        value_logged = self._normalize_value(challenge.challenge_type, payload)

        today = datetime.utcnow().date()
        existing = await self.completion_repo.get_by_user_challenge_date(
            user_id=user_id,
            challenge_id=payload.challenge_id,
            completion_date=today,
        )

        is_counter = (challenge.challenge_type or "").lower() == "counter"
        target = challenge.target_value

        if existing:
            # Counter challenges accumulate toward target_value across multiple
            # submissions in the same day. Block only once the target is met.
            if is_counter and target is not None:
                if (existing.value_logged or 0) >= target:
                    raise BusinessException(message="Already completed today", status_code=409)

                new_total = (existing.value_logged or 0) + (value_logged or 0)
                new_xp, status = self._compute_xp_and_status(
                    challenge_type=challenge.challenge_type,
                    target=target,
                    value=new_total,
                    full_xp=challenge.xp_reward,
                )

                existing.value_logged = new_total
                existing.xp_earned = new_xp
                completion = await self.completion_repo.update(existing)

                return ChallengeActionResponse(
                    message=(
                        "Challenge marked as completed"
                        if status == "done"
                        else "Progress logged"
                    ),
                    xp_earned=completion.xp_earned,
                    status=status,
                    completion_date=today,
                    value_logged=completion.value_logged,
                )

            raise BusinessException(message="Already completed today", status_code=409)

        xp_earned, status = self._compute_xp_and_status(
            challenge_type=challenge.challenge_type,
            target=target,
            value=value_logged,
            full_xp=challenge.xp_reward,
        )

        completion = await self.completion_repo.create(
            UserChallengeCompletion(
                user_id=user_id,
                challenge_id=payload.challenge_id,
                company_id=company_user.company_id,
                completion_date=today,
                value_logged=value_logged,
                xp_earned=xp_earned,
            )
        )

        return ChallengeActionResponse(
            message=(
                "Challenge marked as completed"
                if status == "done"
                else "Progress logged"
            ),
            xp_earned=completion.xp_earned,
            status=status,
            completion_date=today,
            value_logged=completion.value_logged,
        )

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
        if ctype in ("counter", "timer", "rating"):
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
