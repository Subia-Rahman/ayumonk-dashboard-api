"""Service backing ``GET /api/v1/challenges/schedule``.

Reads the full schedule from ``kpi_challenges`` joined with ``kpis``,
``challenges``, and (left-) ``themes``. Status + date math is computed
in SQL so the result rows hit Python already-shaped. ``kpi_summary`` is
built in a single Python pass over ``items`` — no second round-trip.

Status semantics (spec section 6.4):
    paused   — is_active = FALSE
    upcoming — today < start_date
    ended    — end_date IS NOT NULL AND today > end_date
    active   — otherwise

KPI-level rollup precedence (kpi_summary[].status):
    active > upcoming > paused > ended
That is, a KPI is "active" if *any* of its challenges are active today;
otherwise "upcoming" if any are upcoming; otherwise "paused" if any are
paused; otherwise "ended".
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession


# Status precedence for the per-KPI rollup. Higher value wins when
# combining multiple challenges under the same kpi_key.
_KPI_STATUS_PRECEDENCE: dict[str, int] = {
    "ended": 0,
    "paused": 1,
    "upcoming": 2,
    "active": 3,
}


# Single SQL covering the full timeline. Status + date arithmetic are
# computed inline so the result rows hit Python already-shaped. Status
# precedence in the CASE order matches the spec's state-machine
# (paused first because is_active=FALSE wins regardless of dates).
_SCHEDULE_SQL = """
SELECT
    kc.id                                            AS kpi_challenge_id,
    kc.kpi_key                                       AS kpi_key,
    COALESCE(k.display_name, '')                     AS kpi_label,
    kc.challenge_key                                 AS challenge_key,
    COALESCE(ch.name, '')                            AS challenge_label,
    ch.icon                                          AS challenge_icon,
    COALESCE(ch.challenge_type, '')                  AS challenge_type,
    k.theme_key                                      AS theme_key,
    t.theme_display_name                             AS theme_label,
    kc.start_date                                    AS start_date,
    kc.end_date                                      AS end_date,
    kc.is_active                                     AS is_active,
    CASE
        WHEN kc.is_active = FALSE                        THEN 'paused'
        WHEN CURRENT_DATE < kc.start_date                THEN 'upcoming'
        WHEN kc.end_date IS NOT NULL
             AND CURRENT_DATE > kc.end_date              THEN 'ended'
        ELSE 'active'
    END                                              AS status,
    -- days_total / days_remaining are NULL for open-ended schedules
    -- (end_date IS NULL). days_elapsed is always defined.
    CASE
        WHEN kc.end_date IS NULL THEN NULL
        ELSE (kc.end_date - kc.start_date)
    END                                              AS days_total,
    GREATEST(0, CURRENT_DATE - kc.start_date)        AS days_elapsed,
    CASE
        WHEN kc.end_date IS NULL THEN NULL
        ELSE GREATEST(0, kc.end_date - CURRENT_DATE)
    END                                              AS days_remaining,
    CASE
        WHEN kc.end_date IS NULL THEN NULL
        WHEN (kc.end_date - kc.start_date) <= 0 THEN 100.0
        ELSE ROUND(
            LEAST(100.0, GREATEST(0.0,
                100.0 * (CURRENT_DATE - kc.start_date)
                       / (kc.end_date - kc.start_date)::numeric
            ))::numeric, 1
        )
    END                                              AS progress_pct
FROM kpi_challenges kc
JOIN kpis k       ON k.kpi_key = kc.kpi_key
JOIN challenges ch ON ch.challenge_key = kc.challenge_key
LEFT JOIN themes t ON t.theme_key = k.theme_key
WHERE kc.is_deleted = FALSE
  AND (CAST(:company_id AS UUID) IS NULL OR kc.company_id = CAST(:company_id AS UUID))
  AND (CAST(:kpi_key    AS UUID) IS NULL OR kc.kpi_key    = CAST(:kpi_key    AS UUID))
ORDER BY kc.start_date ASC, k.display_name ASC, ch.name ASC
"""


class ChallengeScheduleService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_schedule(
        self,
        *,
        company_id: Optional[UUID],
        status_filter: Optional[set[str]] = None,
        kpi_key: Optional[UUID] = None,
    ) -> dict:
        """Return ``{"items": [...], "kpi_summary": [...]}``.

        ``company_id`` — None means "all companies" (only platform admins
        should hit that branch; callers enforce tenant scope upstream).
        ``status_filter`` — None means "no narrowing"; otherwise a set of
        wire-format statuses to keep.
        ``kpi_key`` — optional narrow to one KPI.
        """
        rows = (
            await self.db.execute(
                sql_text(_SCHEDULE_SQL),
                {"company_id": company_id, "kpi_key": kpi_key},
            )
        ).mappings().all()

        # Filter post-SQL because status is computed there and we want a
        # single source of truth for the CASE expression.
        items: list[dict] = []
        for row in rows:
            status = row["status"]
            if status_filter and status not in status_filter:
                continue
            items.append(_row_to_item(row))

        kpi_summary = _build_kpi_summary(items)
        return {"items": items, "kpi_summary": kpi_summary}


def _row_to_item(row) -> dict:
    """Convert a SQL row (RowMapping) to the dict shape the schema expects.

    Numeric / Decimal pass-through is fine — Pydantic coerces. Dates and
    UUIDs are passed through as-is."""
    progress = row["progress_pct"]
    return {
        "kpi_challenge_id": row["kpi_challenge_id"],
        "kpi_key": row["kpi_key"],
        "kpi_label": row["kpi_label"] or "",
        "challenge_key": row["challenge_key"],
        "challenge_label": row["challenge_label"] or "",
        "challenge_icon": row["challenge_icon"],
        "challenge_type": row["challenge_type"] or "",
        "theme_key": row["theme_key"],
        "theme_label": row["theme_label"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "is_active": bool(row["is_active"]),
        "status": row["status"],
        "days_total": (
            int(row["days_total"]) if row["days_total"] is not None else None
        ),
        "days_elapsed": int(row["days_elapsed"] or 0),
        "days_remaining": (
            int(row["days_remaining"]) if row["days_remaining"] is not None else None
        ),
        "progress_pct": (
            Decimal(str(progress)) if progress is not None else None
        ),
    }


def _build_kpi_summary(items: list[dict]) -> list[dict]:
    """Group items by ``kpi_key`` in a single pass; pick the highest-
    precedence status across the KPI's challenges, the earliest start,
    and the latest end (None if any challenge is open-ended).

    Stable order: by earliest_start asc, then kpi_label asc — same
    ordering rule the per-item SQL uses for its `ORDER BY`."""
    grouped: dict[UUID, dict] = {}
    for item in items:
        kpi_key = item["kpi_key"]
        bucket = grouped.get(kpi_key)
        if bucket is None:
            bucket = {
                "kpi_key": kpi_key,
                "kpi_label": item["kpi_label"],
                "earliest_start": item["start_date"],
                "latest_end": item["end_date"],
                "open_ended": item["end_date"] is None,
                "status": item["status"],
                "challenge_count": 1,
            }
            grouped[kpi_key] = bucket
            continue

        bucket["challenge_count"] += 1

        # Earliest start always tightens.
        if item["start_date"] < bucket["earliest_start"]:
            bucket["earliest_start"] = item["start_date"]

        # latest_end: NULL if any challenge under this KPI is open-ended,
        # else the maximum end_date among bounded challenges.
        if item["end_date"] is None:
            bucket["open_ended"] = True
            bucket["latest_end"] = None
        elif not bucket["open_ended"]:
            if bucket["latest_end"] is None or item["end_date"] > bucket["latest_end"]:
                bucket["latest_end"] = item["end_date"]

        # Status: keep the higher-precedence one.
        if _KPI_STATUS_PRECEDENCE[item["status"]] > _KPI_STATUS_PRECEDENCE[bucket["status"]]:
            bucket["status"] = item["status"]

    summary = [
        {
            "kpi_key": b["kpi_key"],
            "kpi_label": b["kpi_label"],
            "earliest_start": b["earliest_start"],
            "latest_end": b["latest_end"],
            "status": b["status"],
            "challenge_count": b["challenge_count"],
        }
        for b in grouped.values()
    ]
    summary.sort(key=lambda b: (b["earliest_start"], b["kpi_label"]))
    return summary
