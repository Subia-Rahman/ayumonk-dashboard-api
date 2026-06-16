from __future__ import annotations
"""Phase 3 — Wellness Index computation + persistence.

This service is the single source of truth for the
``theme_submission_scores`` row written after every wellness-form
submission. Both submission entry points
(``sessions.submit_form`` and ``employee_form.process_submission``) call
``persist_for_response()`` immediately after their final answer insert,
so the WI is durable and ``GET /api/v1/wellness/index`` is a plain
lookup instead of an aggregate-on-read every time.

Why a dedicated service:
  * Centralises the WI formula. The existing ``v_user_wellness_index``
    view encodes the read-time computation
    ``((Σ(score·wi_weight) / Σ(wi_weight)) - 1) / 4 * 100`` clamped
    [0, 100]; this service mirrors it for the write-time path so the
    persisted number agrees with the view to the second decimal.
  * Resolves the spec's reverse-scoring rule
    (``final_score = 6 - raw`` when ``kpi_questions.reverse_code = TRUE``)
    in one place. Today both submission paths store raw scores; this
    service rewrites them to final_score before averaging so the WI is
    correctly signed for reverse-coded KPIs (e.g. STRESS_KPI).

The risk-band thresholds match spec Section 8 / Table 3 (excellent
80-100 / good 60-79 / moderate 40-59 / attention 0-39).
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.theme_submission_score import ThemeSubmissionScore


# Risk-band thresholds — spec Section 8 / Table 3. Order matters: list
# from highest band to lowest so the first matching min is the answer.
_RISK_BANDS: tuple[tuple[Decimal, str], ...] = (
    (Decimal("80"), "excellent"),
    (Decimal("60"), "good"),
    (Decimal("40"), "moderate"),
    (Decimal("0"),  "attention"),
)


# Pull (kpi_key, score, reverse_code) for every answer attached to a single
# response. ``score`` is the raw form-stored value (1-5); reverse_code
# rewriting happens in Python so the SQL stays readable.
_RESPONSE_ANSWERS_SQL = """
SELECT
    q.kpi               AS kpi_key,
    efa.score::numeric  AS score,
    COALESCE(q.reverse_code, FALSE) AS reverse_code
FROM employee_form_answer efa
JOIN kpi_questions q
    ON  q.question_code = efa.question_code
    AND q.is_deleted    = FALSE
WHERE efa.response_id = :response_id
  AND efa.is_deleted  = FALSE
"""


# wi_weight per KPI (defaults to 0.10 to match the view's COALESCE).
_KPI_WEIGHTS_SQL = """
SELECT kpi_key, COALESCE(wi_weight, 0.10) AS wi_weight
FROM kpis
WHERE kpi_key = ANY(:kpi_keys)
  AND is_active  = TRUE
  AND is_deleted = FALSE
"""


# Previous submission's score for the same employee — used for week_delta.
# Ordered desc so the first row is the most recent prior submission.
_PREVIOUS_SCORE_SQL = """
SELECT overall_score
FROM theme_submission_scores
WHERE employee_email = :email
  AND is_deleted     = FALSE
ORDER BY created_at DESC
LIMIT 1
"""


# Resolve a theme for the company directly from the themes table.
# Themes are company-scoped via themes.company_id, so we just pick the
# first active theme for the company (deterministic by display name to
# match ThemeRepository.list ordering).
#
# Time-boundation lives on KPIs and challenges (their own start_date /
# end_date), not at the theme level — so we don't filter the theme by
# date here.
#
# The ::uuid cast happens only when :company_id is UUID-shaped (the
# regexp guard); legacy non-UUID company_id values from
# employee_form_response simply produce zero rows instead of raising,
# leaving theme_key NULL on the persisted WI row.
_RESOLVE_THEME_SQL = """
SELECT theme_key
FROM themes
WHERE company_id = (
        CASE WHEN :company_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
             THEN CAST(:company_id AS UUID) END
      )
  AND is_active  = TRUE
  AND is_deleted = FALSE
ORDER BY theme_display_name ASC
LIMIT 1
"""


def _risk_band(score: Decimal) -> str:
    """Map a 0-100 WI to one of the four spec-defined bands."""
    for floor, label in _RISK_BANDS:
        if score >= floor:
            return label
    return "attention"


def _final_score(raw: Decimal, reverse_code: bool) -> Decimal:
    """Apply the spec's reverse-scoring rule.

    For reverse-coded questions (e.g. "I feel very stressed"), a high
    raw answer means a *worse* outcome — so the WI must treat it as
    ``6 - raw``. For normal questions the raw 1-5 is already correctly
    signed."""
    if reverse_code:
        return Decimal("6") - Decimal(raw)
    return Decimal(raw)


class WellnessScoringService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _resolve_theme_key(self, company_id: Optional[str]) -> Optional[UUID]:
        """Best-effort lookup of a theme_key for a given company. Returns
        None when company_id is missing or non-UUID-shaped (legacy values
        like 'COMPANY_123' in employee_form_response) or when no active
        theme is configured for that company yet."""
        if not company_id:
            return None
        try:
            result = await self.db.execute(
                sql_text(_RESOLVE_THEME_SQL), {"company_id": str(company_id)}
            )
            return result.scalar_one_or_none()
        except Exception:
            # Defensive — never let a theme-resolution issue fail the
            # write path that called persist_for_response.
            return None

    async def persist_for_response(
        self,
        *,
        response_id: str,
        employee_email: str,
        company_id: Optional[str] = None,
        theme_key: Optional[UUID] = None,
        user_id: Optional[int] = None,
    ) -> Optional[ThemeSubmissionScore]:
        """Compute and persist the WI for a freshly-written response.

        Returns the newly inserted ``ThemeSubmissionScore``, or None when
        the submission has no scorable answers (degenerate case — e.g.
        a session of only free-text questions).

        Idempotent on ``response_id``: if a row already exists for this
        response (e.g. submission re-processed), the previous row is
        returned as-is without writing again. The UNIQUE constraint on
        ``response_id`` enforces this at the DB layer too.
        """
        # Idempotency check — never overwrite an existing WI row.
        existing_stmt = select(ThemeSubmissionScore).where(
            ThemeSubmissionScore.response_id == response_id
        )
        existing = (await self.db.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            return existing

        # 1. Pull every per-question (kpi, raw_score, reverse_code) for
        #    this submission.
        rows = (
            await self.db.execute(
                sql_text(_RESPONSE_ANSWERS_SQL),
                {"response_id": response_id},
            )
        ).all()
        if not rows:
            # No scorable answers — skip persistence. /wellness/index will
            # fall back to the previous submission for this employee.
            return None

        # 2. Apply reverse-scoring rewrite + average per-KPI in Python.
        #    The per-KPI average is what the WI formula expects (one
        #    score per KPI, not one per question).
        per_kpi_scores: dict = {}
        for kpi_key, raw_score, reverse_code in rows:
            if kpi_key is None or raw_score is None:
                continue
            final = _final_score(raw_score, bool(reverse_code))
            per_kpi_scores.setdefault(kpi_key, []).append(final)

        if not per_kpi_scores:
            return None

        per_kpi_avg: dict = {
            kpi_key: sum(scores) / Decimal(len(scores))
            for kpi_key, scores in per_kpi_scores.items()
        }

        # 3. Fetch wi_weight per KPI. Missing rows (KPI deleted /
        #    inactive between submission and now) default to 0.10 — same
        #    rule v_user_wellness_index uses.
        weight_rows = (
            await self.db.execute(
                sql_text(_KPI_WEIGHTS_SQL),
                {"kpi_keys": list(per_kpi_avg.keys())},
            )
        ).all()
        wi_weights: dict = {row[0]: Decimal(str(row[1])) for row in weight_rows}
        for kpi_key in per_kpi_avg:
            wi_weights.setdefault(kpi_key, Decimal("0.10"))

        # 4. WI formula — mirrors v_user_wellness_index exactly:
        #    ((Σ(score·weight) / Σ(weight)) - 1) / 4 * 100, clamped [0,100].
        numerator = sum(per_kpi_avg[k] * wi_weights[k] for k in per_kpi_avg)
        denominator = sum(wi_weights[k] for k in per_kpi_avg)
        if denominator == 0:
            return None

        avg = numerator / denominator
        overall = ((avg - Decimal("1")) / Decimal("4")) * Decimal("100")
        if overall < 0:
            overall = Decimal("0")
        elif overall > 100:
            overall = Decimal("100")
        overall = overall.quantize(Decimal("0.01"))

        # 5. Week delta — diff against the same employee's previous WI
        #    (most recent prior theme_submission_scores row, regardless
        #    of when). NULL when no prior submission exists.
        prev = (
            await self.db.execute(
                sql_text(_PREVIOUS_SCORE_SQL),
                {"email": employee_email},
            )
        ).scalar_one_or_none()
        week_delta: Optional[Decimal] = None
        if prev is not None:
            week_delta = (overall - Decimal(str(prev))).quantize(Decimal("0.01"))

        # 6. Resolve theme — caller-supplied takes precedence; otherwise
        #    fall back to the first active theme for the company. May be
        #    None when no theme is configured yet (Phase 5 will tighten
        #    this via the company_themes assignment table).
        resolved_theme_key = theme_key
        if resolved_theme_key is None:
            resolved_theme_key = await self._resolve_theme_key(company_id)

        # 7. Persist. The DB UNIQUE constraint on response_id catches the
        #    rare race where two concurrent submissions try to write the
        #    same row; the idempotency check above handles the common
        #    case without a unique-violation round-trip.
        row = ThemeSubmissionScore(
            response_id=response_id,
            company_id=company_id,
            employee_email=employee_email,
            theme_key=resolved_theme_key,
            overall_score=overall,
            risk_level=_risk_band(overall),
            week_delta=week_delta,
            created_by=user_id,
            updated_by=user_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row
