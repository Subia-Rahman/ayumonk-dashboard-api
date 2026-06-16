from __future__ import annotations
"""Service backing GET /api/v1/dashboard/employee-snapshots.

Returns one row per active employee for a company with all wellness/CXO
metrics pre-computed, so the HR Analytics dashboard can do its own
grouping/averaging client-side. Reads:

* `company_users` / `departments` / `companies` / `locations` for demographics
* `v_user_kpi_score` (pivoted to Sleep / Stress / Nutrition columns)
* `v_user_wellness_index` for the WI 0-100 value
* `v_user_cxo` for Productivity + Absenteeism (already pivoted there)
* `compute_user_engagement(user_id)` for Engagement (called per row — the
  PL/pgSQL function encodes the same WELLNESS_INDEX / CHALLENGE_RATE_30D /
  FORM_RATE_90D / MOOD_AVG fallback logic the spec describes, so we don't
  duplicate it in Python)

Plus two introspection queries for `meta.missingMappings` and
`meta.missingKpis`.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.config import APP_TZ


# Display names the dashboard pivots into top-level columns. Compared via
# LOWER(TRIM(...)) against `kpis.display_name` — the same fragile lookup
# flagged in cxo_seeder. Follow-up: introduce a `kpis.kpi_code` controlled
# vocabulary so this becomes brittle-name-proof.
_KPI_PIVOT_NAMES: tuple[str, ...] = ("Sleep", "Stress", "Nutrition")

_CXO_METRIC_CODES: tuple[str, ...] = ("PRODUCTIVITY", "ENGAGEMENT", "ABSENTEEISM")


# ---------------------------------------------------------------------------
# Main query — one composite read per request.
#
# Per-employee LATERAL call to compute_user_engagement(user_id) keeps the
# engagement formula single-sourced in the PL/pgSQL function. If the perf
# budget (<300ms @ 1k employees, <1s @ 5k) starts to bite, inline the
# engagement CTE here and drop the function call.
# ---------------------------------------------------------------------------
_SNAPSHOTS_SQL = """
WITH employees AS (
    SELECT
        cu.id          AS user_id,
        cu.age_band    AS age,
        cu.gender      AS gender,
        d.name         AS dept,
        l.name         AS loc
    FROM company_users cu
    JOIN companies c     ON c.id = cu.company_id
    LEFT JOIN departments d ON d.id = cu.department_id
    LEFT JOIN locations  l ON l.id = c.location_id
    WHERE cu.company_id = :company_id
      AND cu.is_active   = TRUE
      AND cu.is_deleted  = FALSE
),
kpi_pivot AS (
    SELECT
        v.user_id,
        MAX(v.score) FILTER (WHERE LOWER(TRIM(k.display_name)) = 'sleep')     AS sleep,
        MAX(v.score) FILTER (WHERE LOWER(TRIM(k.display_name)) = 'stress')    AS stress,
        MAX(v.score) FILTER (WHERE LOWER(TRIM(k.display_name)) = 'nutrition') AS nutrition
    FROM v_user_kpi_score v
    JOIN kpis k
      ON k.kpi_key   = v.kpi_key
     AND k.company_id = v.company_id
     AND k.is_active  = TRUE
     AND k.is_deleted = FALSE
    WHERE v.company_id = :company_id
    GROUP BY v.user_id
)
SELECT
    e.user_id,
    e.dept,
    e.loc,
    e.age,
    e.gender,
    wi.wellness_index                                AS wellness_index,
    cxo.productivity_pct                             AS productivity,
    cxo.absenteeism_days                             AS absenteeism,
    compute_user_engagement(e.user_id)               AS engagement,
    kp.sleep,
    kp.stress,
    kp.nutrition
FROM employees e
LEFT JOIN v_user_wellness_index wi ON wi.user_id = e.user_id
LEFT JOIN v_user_cxo            cxo ON cxo.user_id = e.user_id
LEFT JOIN kpi_pivot             kp  ON kp.user_id  = e.user_id
ORDER BY e.user_id
"""


# `cxo_metric_kpi_mapping` powers WEIGHTED_AVG (PRODUCTIVITY) and DEFICIT_SUM
# (ABSENTEEISM); `cxo_metric_signal_mapping` powers COMPOSITE (ENGAGEMENT).
# Distinct master rows per company now (post per-company refactor), so the
# join key is master.company_id, not metric_code alone.
_MISSING_MAPPINGS_SQL = """
SELECT m.metric_code
FROM cxo_metric_master m
WHERE m.company_id = :company_id
  AND m.is_active   = TRUE
  AND m.is_deleted  = FALSE
  AND m.metric_code = ANY(:metric_codes)
  AND NOT EXISTS (
    SELECT 1
      FROM cxo_metric_kpi_mapping kmap
     WHERE kmap.metric_id  = m.id
       AND kmap.company_id = m.company_id
       AND kmap.is_active  = TRUE
       AND kmap.is_deleted = FALSE
  )
  AND NOT EXISTS (
    SELECT 1
      FROM cxo_metric_signal_mapping smap
     WHERE smap.metric_id  = m.id
       AND smap.company_id = m.company_id
       AND smap.is_active  = TRUE
       AND smap.is_deleted = FALSE
  )
"""


# Which of (Sleep, Stress, Nutrition) the company does NOT have a KPI for —
# matched by LOWER(TRIM(display_name)) (the same fragile lookup the seeder
# uses; see TODO above).
_MISSING_KPIS_SQL = """
SELECT name
FROM unnest(:names) AS u(name)
WHERE NOT EXISTS (
  SELECT 1
    FROM kpis k
   WHERE k.company_id = :company_id
     AND k.is_active  = TRUE
     AND k.is_deleted = FALSE
     AND LOWER(TRIM(k.display_name)) = LOWER(TRIM(u.name))
)
"""


# Whether master rows even exist for this company. A company that hasn't
# been seeded yet would otherwise show *no* missing mappings (because the
# master rows are absent, so the NOT EXISTS join above doesn't even fire),
# which is misleading.
_MISSING_MASTER_SQL = """
SELECT code
FROM unnest(:metric_codes) AS u(code)
WHERE NOT EXISTS (
  SELECT 1
    FROM cxo_metric_master m
   WHERE m.company_id  = :company_id
     AND m.metric_code = u.code
     AND m.is_active   = TRUE
     AND m.is_deleted  = FALSE
)
"""


def _to_float(value: Any) -> float | None:
    """Numeric columns come back as `Decimal` from asyncpg. The dashboard
    wants JSON numbers, so coerce. NULLs stay NULL."""
    if value is None:
        return None
    return float(value)


class EmployeeSnapshotsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def fetch(self, *, company_id: UUID) -> dict[str, Any]:
        rows = (await self.db.execute(
            sql_text(_SNAPSHOTS_SQL), {"company_id": company_id}
        )).mappings().all()

        # Coerce Decimal -> float and drop the user_id (internal only).
        data = [
            {
                "dept":          row["dept"],
                "loc":           row["loc"],
                "age":           row["age"],
                "gender":        row["gender"],
                "wellnessIndex": _to_float(row["wellness_index"]),
                "productivity":  _to_float(row["productivity"]),
                "engagement":    _to_float(row["engagement"]),
                "absenteeism":   _to_float(row["absenteeism"]),
                "sleep":         _to_float(row["sleep"]),
                "stress":        _to_float(row["stress"]),
                "nutrition":     _to_float(row["nutrition"]),
            }
            for row in rows
        ]

        # Master rows missing (company never seeded) AND mapping rows missing
        # (master exists but unmapped) both surface in missingMappings. The
        # union is deduped + ordered to match the canonical metric_code list
        # so the dashboard sees a stable response shape.
        missing_master_rows = (await self.db.execute(
            sql_text(_MISSING_MASTER_SQL),
            {
                "company_id":    company_id,
                "metric_codes":  list(_CXO_METRIC_CODES),
            },
        )).all()
        missing_master = {r[0] for r in missing_master_rows}

        unmapped_rows = (await self.db.execute(
            sql_text(_MISSING_MAPPINGS_SQL),
            {
                "company_id":    company_id,
                "metric_codes":  list(_CXO_METRIC_CODES),
            },
        )).all()
        unmapped = {r[0] for r in unmapped_rows}

        missing_mappings = [
            code for code in _CXO_METRIC_CODES
            if code in missing_master or code in unmapped
        ]

        missing_kpi_rows = (await self.db.execute(
            sql_text(_MISSING_KPIS_SQL),
            {
                "company_id":  company_id,
                "names":       list(_KPI_PIVOT_NAMES),
            },
        )).all()
        # Preserve canonical order so the response is stable.
        missing_kpi_set = {r[0] for r in missing_kpi_rows}
        missing_kpis = [name for name in _KPI_PIVOT_NAMES if name in missing_kpi_set]

        return {
            "data": data,
            "meta": {
                "companyId":            company_id,
                "totalEmployees":       len(data),
                "updatedAt":            datetime.now(APP_TZ),
                "missingMappings":      missing_mappings,
                "missingKpis":          missing_kpis,
                "locationGranularity":  "company",
            },
        }
