"""Phase 4 — Two-tier suggestion engine + persistence.

This module owns the **write-time** suggestion engine — it runs once per
form submission, inside the same write path that persists the Wellness
Index, and inserts up to 6 ``user_suggestion_log`` rows (2 Aahar + 2
Vihar + 2 Aushadh) for the employee to see in their Lifestyle
Suggestions Panel.

Why persist at submission time instead of computing on read:
  * The Lifestyle Suggestions Panel needs to show the SAME 6 cards every
    time the employee opens the dashboard, not re-roll them per page
    load. Persisting freezes the engine output.
  * The "did this suggestion work?" feedback loop (action = done /
    skipped / saved) is per-row — without persistence there's no row to
    attach the action to.
  * Per-submission audit trail — we can answer "what was served on day
    X and what did they do with it?" in one table scan.

Engine algorithm (spec §9 — Two-Tier Trigger Design):

  Tier 1 — KPI-Level (trigger_mode='kpi_risk'):
    For each KPI in moderate/risk band (avg score < 4.0), pick mappings
    where risk_level matches the band.

  Tier 2 — Question-Level (trigger_mode='question_score'):
    For each individual question, pick mappings where the question's
    score crosses ``score_threshold_below`` or ``score_threshold_above``.

  Combined (trigger_mode='both'):
    Mapping must satisfy BOTH the KPI risk-band AND the question-score
    threshold. Highest specificity — used sparingly for surgical
    interventions.

After matching, filter by dosha (``Suggestion.dosha_type IN ('all',
:user_dosha)``), then dedupe by suggestion_id, then group by
``suggestion_type`` and take the top 2-by-priority per type. Returns a
flat list capped at 6.

Today's `users.dosha_type` gap: the company_users table doesn't carry a
dosha column yet (the Prakriti onboarding quiz is a separate phase). The
engine accepts ``user_dosha=None`` and degrades to "match all
dosha_type='all' suggestions only" — the same behaviour the spec calls
out for users who haven't completed the assessment.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.kpi_suggestion_mapping import KPISuggestionMapping
from config_service.app.models.suggestion import Suggestion
from config_service.app.models.user_suggestion_log import UserSuggestionLog
from config_service.app.repositories.employee_form import EmployeeFormRepository


# Risk-band thresholds — must match SessionService.get_suggestions_for_user
# (sessions.py:723-728) so the persisted engine output agrees with the
# existing read-on-demand endpoint. Mirrors spec §9.1.
def _classify_kpi(avg: float) -> str:
    if avg >= 4.0:
        return "good"
    if avg >= 3.0:
        return "moderate"
    return "risk"


# Max items per suggestion_type the spec calls for (2 Aahar + 2 Vihar + 2
# Aushadh = up to 6 total). Engine caps each type at this value after
# priority sort.
_MAX_PER_TYPE = 2


class SuggestionEngineService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def compute_and_persist(
        self,
        *,
        response_id: str,
        employee_email: str,
        company_id: Optional[str] = None,
        user_id: Optional[UUID] = None,
        user_dosha: Optional[str] = None,
        actor_user_id: Optional[int] = None,
    ) -> list[UserSuggestionLog]:
        """Run the engine for one submission and persist the picks.

        Returns the inserted ``user_suggestion_log`` rows (may be empty
        when no KPIs are in moderate/risk band or no mappings exist).

        Idempotent on ``response_id``: if rows already exist for this
        submission, returns them as-is without writing again. The UNIQUE
        (response_id, suggestion_id) constraint enforces this at the DB
        layer too.
        """
        # Idempotency check — never overwrite an existing engine run.
        existing_stmt = select(UserSuggestionLog).where(
            UserSuggestionLog.response_id == response_id
        )
        existing = (await self.db.execute(existing_stmt)).scalars().all()
        if existing:
            return list(existing)

        # 1. Pull per-question scores joined with KPI metadata for this
        #    submission. Reuses the existing repository helper that
        #    SessionService.get_suggestions_for_user already relies on
        #    so the engine output agrees with the on-demand endpoint.
        form_repo = EmployeeFormRepository(self.db)
        rows = await form_repo.get_answers_with_kpi(response_id)
        if not rows:
            return []

        # 2. Build KPI averages + per-question scores. Mirrors
        #    SessionService.get_suggestions_for_user (sessions.py:694-721)
        #    — same shape so the two paths stay consistent.
        kpi_stats: dict = {}
        question_scores: dict = {}
        for row in rows:
            kpi_key = row.kpi_key
            score = float(row.score or 0)
            if kpi_key is None:
                continue
            if kpi_key not in kpi_stats:
                kpi_stats[kpi_key] = {"total": 0.0, "count": 0}
            kpi_stats[kpi_key]["total"] += score
            kpi_stats[kpi_key]["count"] += 1
            question_scores[row.question_key] = {
                "kpi_key": kpi_key,
                "score": score,
            }
        kpi_averages = {
            k: (v["total"] / v["count"]) if v["count"] else 0.0
            for k, v in kpi_stats.items()
        }
        kpi_levels = {k: _classify_kpi(avg) for k, avg in kpi_averages.items()}

        # 3. Fetch Tier-1 mappings (kpi_risk + both) for at-risk KPIs.
        at_risk_kpis = [k for k, lvl in kpi_levels.items() if lvl in {"moderate", "risk"}]
        at_risk_levels = {kpi_levels[k] for k in at_risk_kpis}
        kpi_mappings = []
        if at_risk_kpis:
            kpi_mappings = await self._fetch_kpi_mappings(
                kpi_keys=at_risk_kpis,
                risk_levels=at_risk_levels,
                user_dosha=user_dosha,
            )

        # 4. Fetch Tier-2 mappings (question_score + both) for every
        #    answered question. Filtering by threshold happens in Python
        #    since the threshold direction depends on the mapping row.
        question_mappings = []
        if question_scores:
            question_mappings = await self._fetch_question_mappings(
                question_keys=list(question_scores.keys()),
                user_dosha=user_dosha,
            )

        # 5. Build per-suggestion candidates with best (lowest) priority
        #    and a sample kpi_key + trigger_mode for the audit row.
        picks: dict = {}

        for mapping, suggestion in kpi_mappings:
            level = kpi_levels.get(mapping.kpi_key)
            if not level or level == "good":
                continue
            self._record_pick(
                picks=picks,
                suggestion=suggestion,
                kpi_key=mapping.kpi_key,
                trigger_mode=mapping.trigger_mode,
                priority=mapping.priority,
            )

        for mapping, suggestion in question_mappings:
            qs = question_scores.get(mapping.question_key)
            if not qs:
                continue
            score = qs["score"]
            below = mapping.score_threshold_below
            above = mapping.score_threshold_above
            matched = (below is not None and score < below) or (
                above is not None and score > above
            )
            if not matched:
                continue
            # `trigger_mode='both'` mappings additionally require the KPI
            # to be at the declared risk_level — enforce here so a Tier-2
            # match alone doesn't fire a `both` mapping.
            mode = (mapping.trigger_mode or "").lower()
            if mode == "both":
                expected_level = (mapping.risk_level or "").lower()
                actual_level = kpi_levels.get(qs["kpi_key"])
                if not actual_level or actual_level != expected_level:
                    continue
            self._record_pick(
                picks=picks,
                suggestion=suggestion,
                kpi_key=qs["kpi_key"],
                trigger_mode=mapping.trigger_mode,
                priority=mapping.priority,
            )

        if not picks:
            return []

        # 6. Group by suggestion_type and take top-2 by priority per type.
        #    This is the spec's "2 Aahar + 2 Vihar + 2 Aushadh" shape.
        by_type: dict = {}
        for pick in picks.values():
            by_type.setdefault((pick["suggestion_type"] or "").lower(), []).append(pick)
        chosen: list[dict] = []
        for stype_picks in by_type.values():
            stype_picks.sort(key=lambda p: (p["priority"], str(p["suggestion_id"])))
            chosen.extend(stype_picks[:_MAX_PER_TYPE])

        # 7. Persist. Sort the final list by priority asc for a stable
        #    write order (matches read-time sort in get_my_latest).
        chosen.sort(key=lambda p: (p["priority"], str(p["suggestion_id"])))
        now = datetime.utcnow()
        log_rows = [
            UserSuggestionLog(
                response_id=response_id,
                employee_email=employee_email,
                company_id=company_id,
                user_id=user_id,
                suggestion_id=p["suggestion_id"],
                kpi_key=p["kpi_key"],
                trigger_mode=p["trigger_mode"],
                priority=p["priority"],
                shown_at=now,
                created_at=now,
                updated_at=now,
                created_by=actor_user_id,
                updated_by=actor_user_id,
            )
            for p in chosen
        ]
        for row in log_rows:
            self.db.add(row)
        await self.db.commit()
        for row in log_rows:
            await self.db.refresh(row)
        return log_rows

    # -----------------------------------------------------------------------
    # internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _record_pick(
        *,
        picks: dict,
        suggestion: Suggestion,
        kpi_key,
        trigger_mode: str,
        priority: int,
    ) -> None:
        """Track the best (lowest-priority) mapping per suggestion_id and
        carry over its (kpi_key, trigger_mode) for the audit row."""
        existing = picks.get(suggestion.id)
        if existing is None or priority < existing["priority"]:
            picks[suggestion.id] = {
                "suggestion_id": suggestion.id,
                "suggestion_type": suggestion.suggestion_type,
                "kpi_key": kpi_key,
                "trigger_mode": trigger_mode,
                "priority": priority,
            }

    async def _fetch_kpi_mappings(
        self,
        *,
        kpi_keys: list,
        risk_levels: set,
        user_dosha: Optional[str],
    ) -> list:
        from sqlalchemy import func

        stmt = (
            select(KPISuggestionMapping, Suggestion)
            .join(Suggestion, Suggestion.id == KPISuggestionMapping.suggestion_id)
            .where(
                KPISuggestionMapping.is_deleted == False,  # noqa: E712
                KPISuggestionMapping.is_active == True,  # noqa: E712
                Suggestion.is_deleted == False,  # noqa: E712
                Suggestion.is_active == True,  # noqa: E712
                KPISuggestionMapping.kpi_key.in_(kpi_keys),
                func.lower(KPISuggestionMapping.trigger_mode).in_(["kpi_risk", "both"]),
                func.lower(KPISuggestionMapping.risk_level).in_(
                    [lvl.lower() for lvl in risk_levels]
                ),
                Suggestion.dosha_type.in_(_dosha_filter_values(user_dosha)),
            )
        )
        return (await self.db.execute(stmt)).all()

    async def _fetch_question_mappings(
        self,
        *,
        question_keys: list,
        user_dosha: Optional[str],
    ) -> list:
        from sqlalchemy import func

        stmt = (
            select(KPISuggestionMapping, Suggestion)
            .join(Suggestion, Suggestion.id == KPISuggestionMapping.suggestion_id)
            .where(
                KPISuggestionMapping.is_deleted == False,  # noqa: E712
                KPISuggestionMapping.is_active == True,  # noqa: E712
                Suggestion.is_deleted == False,  # noqa: E712
                Suggestion.is_active == True,  # noqa: E712
                KPISuggestionMapping.question_key.in_(question_keys),
                func.lower(KPISuggestionMapping.trigger_mode).in_(
                    ["question_score", "both"]
                ),
                Suggestion.dosha_type.in_(_dosha_filter_values(user_dosha)),
            )
        )
        return (await self.db.execute(stmt)).all()


def _dosha_filter_values(user_dosha: Optional[str]) -> list[str]:
    """Return the set of ``suggestion.dosha_type`` values that should
    match for a user. Always includes 'all'; appends the user's specific
    dosha when known. Acceptable today's gap (no company_users.dosha_type
    yet) — when the Prakriti assessment lands and starts feeding a
    column, just thread it through ``user_dosha``."""
    values = ["all"]
    if user_dosha:
        normalized = user_dosha.strip().lower()
        if normalized and normalized != "all":
            values.append(normalized)
    return values
