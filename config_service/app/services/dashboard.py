from datetime import datetime

from config_service.app.repositories.kpi import KPIRepository
from config_service.app.repositories.kpi_challenge import KPIChallengeRepository
from config_service.app.repositories.sessions import SessionRepository
from config_service.app.repositories.user_challenge_completions import UserChallengeCompletionRepository
from config_service.app.schemas.dashboard import KPIDashboardCard, KPIDashboardResponse, KPIChallengeBrief
from config_service.app.services.sessions import SessionService


class DashboardService:
    def __init__(self, db):
        self.db = db
        self.session_service = SessionService(SessionRepository(db))
        self.kpi_repo = KPIRepository(db)
        self.kpi_challenge_repo = KPIChallengeRepository(db)
        self.completion_repo = UserChallengeCompletionRepository(db)

    async def get_kpi_cards(self, user_email: str, user_id: int | None = None) -> KPIDashboardResponse:
        submissions = await self.session_service.get_user_submitted_sessions(user_email)

        kpi_entries: dict = {}
        for session in submissions:
            for response in session.get("responses", []):
                submitted_at = response.get("submitted_at")
                if isinstance(submitted_at, str):
                    try:
                        submitted_at = datetime.fromisoformat(submitted_at)
                    except Exception:
                        submitted_at = None
                for kpi in response.get("kpi_scores", []):
                    kpi_key = kpi.get("kpi_key")
                    kpi_name = kpi.get("kpi_name")
                    avg_score = kpi.get("average_score", 0) or 0
                    if kpi_key is None:
                        continue
                    kpi_entries.setdefault(kpi_key, []).append(
                        {
                            "submitted_at": submitted_at,
                            "kpi_name": kpi_name,
                            "average_score": avg_score,
                        }
                    )

        kpi_ids = list(kpi_entries.keys())
        kpis = await self.kpi_repo.list_by_ids(kpi_ids)
        kpi_map = {k.kpi_key: k for k in kpis}

        today = datetime.utcnow().date()
        items: list[KPIDashboardCard] = []

        completion_map: dict = {}
        if user_id is not None:
            todays_completions = await self.completion_repo.list_by_user_date(user_id, today)
            completion_map = {c.challenge_id: c for c in todays_completions}

        for kpi_key, entries in kpi_entries.items():
            entries.sort(key=lambda x: x.get("submitted_at") or datetime.min, reverse=True)
            latest = entries[0]
            prev = entries[1] if len(entries) > 1 else None

            latest_avg = float(latest.get("average_score", 0) or 0)
            prev_avg = float(prev.get("average_score", 0) or 0) if prev else None

            latest_score = round((latest_avg / 5.0) * 100, 2)
            previous_score = round((prev_avg / 5.0) * 100, 2) if prev is not None else None

            trend_percent = None
            if previous_score not in (None, 0):
                trend_percent = round(((latest_score - previous_score) / previous_score) * 100, 2)

            kpi_record = kpi_map.get(kpi_key)
            kpi_start = kpi_record.start_date if kpi_record else None
            kpi_end = kpi_record.end_date if kpi_record else None

            challenge_rows = await self.kpi_challenge_repo.list_by_kpi_and_range(
                kpi_key=kpi_key,
                start_date=today,
                end_date=today,
            )
            challenges = []
            for mapping, challenge in challenge_rows:
                completion = completion_map.get(challenge.challenge_key)
                is_completed_today, value_logged_today = self._completion_state(
                    challenge_type=challenge.challenge_type,
                    target_value=challenge.target_value,
                    completion=completion,
                )
                challenges.append(
                    KPIChallengeBrief(
                        challenge_key=challenge.challenge_key,
                        name=challenge.name,
                        description=challenge.description,
                        icon=challenge.icon,
                        challenge_type=challenge.challenge_type,
                        target_value=challenge.target_value,
                        xp_reward=challenge.xp_reward,
                        is_daily=challenge.is_daily,
                        is_active=challenge.is_active,
                        options=challenge.options,
                        start_date=mapping.start_date,
                        end_date=mapping.end_date,
                        is_completed_today=is_completed_today,
                        value_logged_today=value_logged_today,
                    )
                )

            color = self._score_color(latest_score)
            items.append(
                KPIDashboardCard(
                    kpi_key=kpi_key,
                    kpi_name=latest.get("kpi_name") or (kpi_record.display_name if kpi_record else ""),
                    latest_score=latest_score,
                    previous_score=previous_score,
                    trend_percent=trend_percent,
                    last_submission_at=latest.get("submitted_at"),
                    kpi_start_date=kpi_start,
                    kpi_end_date=kpi_end,
                    color=color,
                    icon=None,
                    challenges=challenges,
                )
            )

        return KPIDashboardResponse(items=items)

    @staticmethod
    def _score_color(score: float) -> str:
        if score >= 80:
            return "#16a34a"
        if score >= 50:
            return "#f59e0b"
        return "#dc2626"

    @staticmethod
    def _completion_state(*, challenge_type, target_value, completion) -> tuple[bool, int | None]:
        # Mirrors the "already completed" rejection in ChallengeActionService:
        # counter accumulates until target is hit; every other type is locked
        # by the first completion of the day.
        if completion is None:
            return False, None
        value_logged = completion.value_logged
        if (challenge_type or "").lower() == "counter" and target_value is not None:
            return (value_logged or 0) >= target_value, value_logged
        return True, value_logged
