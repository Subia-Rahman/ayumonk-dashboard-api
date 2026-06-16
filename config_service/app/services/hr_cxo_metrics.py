from __future__ import annotations
"""Service backing GET /api/v1/hr/cxo-metrics.

Per-employee CXO metric score:
    1. Read active KPI weights for the given metric+company from
       cxo_metric_kpi_mapping.
    2. For each employee, pull the latest-submission KPI scores from
       v_user_kpi_score and require that the employee has a score for EVERY
       mapped KPI.
    3. Normalize each score 1-5 -> 0-100 and combine with weights:
           employee_score = SUM(((score-1)/4*100) * weight) / SUM(weights)
    4. Aggregate by department and by age_band and return both in one payload.
"""

from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.services.hr_filters import (
    EMPLOYEE_DEMOGRAPHIC_FILTERS_SQL,
    HrFilters,
    SUBMISSION_WINDOW_SQL,
    THEME_SCOPE_FILTER_SQL,
)


# Canonical age-band ordering for the by_age_band buckets. Bands outside this
# set are appended in alphabetical order after the canonical ones.
CANONICAL_AGE_BANDS: tuple[str, ...] = (
    "20-25",
    "26-30",
    "31-35",
    "36-40",
    "41-50",
    "50+",
)
_AGE_BAND_RANK: dict[str, int] = {band: idx for idx, band in enumerate(CANONICAL_AGE_BANDS)}


def _age_band_sort_key(label: str) -> tuple[int, str]:
    if label in _AGE_BAND_RANK:
        return (_AGE_BAND_RANK[label], "")
    return (len(CANONICAL_AGE_BANDS), label or "")


# SQL — one round-trip. Both aggregations come out of a single CTE chain so
# we don't recompute per-employee scores twice. Demographic + theme filters
# apply on the cu join feeding per_kpi_score (which would otherwise be a
# straight view scan).
_AGGREGATE_SQL = f"""
WITH mapping AS (
    SELECT map.kpi_key, map.weight
    FROM cxo_metric_kpi_mapping map
    JOIN cxo_metric_master m ON m.id = map.metric_id
    WHERE m.company_id = :company_id
      AND UPPER(m.metric_code) = UPPER(:metric_code)
      AND m.is_active    AND NOT m.is_deleted
      AND map.is_active  AND NOT map.is_deleted
      AND map.company_id = :company_id
),
mapping_stats AS (
    SELECT COUNT(*) AS kpi_count FROM mapping
),
per_kpi_score AS (
    SELECT v.user_id,
           v.department_id,
           v.age_band,
           v.kpi_key,
           ((v.score - 1) / 4.0 * 100.0) AS normalized,
           m.weight
    FROM v_user_kpi_score v
    JOIN mapping m ON m.kpi_key = v.kpi_key
    JOIN company_users cu  ON cu.id      = v.user_id
                           AND cu.is_active  = TRUE
                           AND cu.is_deleted = FALSE
    JOIN companies c       ON c.id       = cu.company_id
    LEFT JOIN departments d ON d.id      = cu.department_id
    LEFT JOIN locations   l ON l.id      = c.location_id
    WHERE v.company_id = :company_id
      {EMPLOYEE_DEMOGRAPHIC_FILTERS_SQL}
      {THEME_SCOPE_FILTER_SQL}
),
employee_score AS (
    SELECT user_id,
           department_id,
           age_band,
           SUM(normalized * weight) / NULLIF(SUM(weight), 0) AS metric_score
    FROM per_kpi_score
    GROUP BY user_id, department_id, age_band
    HAVING COUNT(DISTINCT kpi_key) = (SELECT kpi_count FROM mapping_stats)
)
SELECT 'dept' AS bucket_type,
       COALESCE(d.name, '')                      AS label,
       ROUND(AVG(e.metric_score)::numeric, 1)    AS value
FROM employee_score e
LEFT JOIN departments d ON d.id = e.department_id
WHERE e.department_id IS NOT NULL
GROUP BY d.name

UNION ALL

SELECT 'age_band' AS bucket_type,
       e.age_band AS label,
       ROUND(AVG(e.metric_score)::numeric, 1) AS value
FROM employee_score e
WHERE e.age_band IS NOT NULL AND e.age_band <> ''
GROUP BY e.age_band
"""


# Date-window variant — bypasses v_user_kpi_score for "latest within window"
# semantics. Same final SELECT shape as _AGGREGATE_SQL.
_AGGREGATE_DATE_SQL = f"""
WITH employees AS (
    SELECT
        cu.id              AS user_id,
        cu.email           AS email,
        cu.company_id      AS company_id,
        cu.department_id   AS department_id,
        cu.age_band        AS age_band
    FROM company_users cu
    JOIN companies c          ON c.id = cu.company_id
    LEFT JOIN departments d   ON d.id = cu.department_id
    LEFT JOIN locations   l   ON l.id = c.location_id
    WHERE cu.company_id = :company_id
      AND cu.is_active   = TRUE
      AND cu.is_deleted  = FALSE
      {EMPLOYEE_DEMOGRAPHIC_FILTERS_SQL}
      {THEME_SCOPE_FILTER_SQL}
),
mapping AS (
    SELECT map.kpi_key, map.weight
    FROM cxo_metric_kpi_mapping map
    JOIN cxo_metric_master m ON m.id = map.metric_id
    WHERE m.company_id = :company_id
      AND UPPER(m.metric_code) = UPPER(:metric_code)
      AND m.is_active    AND NOT m.is_deleted
      AND map.is_active  AND NOT map.is_deleted
      AND map.company_id = :company_id
),
mapping_stats AS (
    SELECT COUNT(*) AS kpi_count FROM mapping
),
latest_response AS (
    SELECT DISTINCT ON (efr.employee_email)
        efr.employee_email,
        efr.response_id
    FROM employee_form_response efr
    JOIN employees e ON e.email = efr.employee_email
    WHERE efr.is_deleted       = FALSE
      AND efr.company_id::uuid = :company_id
      {SUBMISSION_WINDOW_SQL}
    ORDER BY efr.employee_email, efr.submitted_at DESC
),
per_kpi_score AS (
    SELECT
        e.user_id,
        e.department_id,
        e.age_band,
        q.kpi                    AS kpi_key,
        ((AVG(efa.score)::numeric - 1) / 4.0 * 100.0) AS normalized,
        m.weight                 AS weight
    FROM employees e
    JOIN latest_response lr        ON lr.employee_email = e.email
    JOIN employee_form_answer efa  ON efa.response_id   = lr.response_id
                                  AND efa.is_deleted    = FALSE
    JOIN kpi_questions q           ON q.question_code   = efa.question_code
                                  AND q.company_id      = e.company_id
                                  AND q.is_deleted      = FALSE
    JOIN mapping m                 ON m.kpi_key = q.kpi
    GROUP BY e.user_id, e.department_id, e.age_band, q.kpi, m.weight
),
employee_score AS (
    SELECT user_id,
           department_id,
           age_band,
           SUM(normalized * weight) / NULLIF(SUM(weight), 0) AS metric_score
    FROM per_kpi_score
    GROUP BY user_id, department_id, age_band
    HAVING COUNT(DISTINCT kpi_key) = (SELECT kpi_count FROM mapping_stats)
)
SELECT 'dept' AS bucket_type,
       COALESCE(d.name, '')                      AS label,
       ROUND(AVG(e.metric_score)::numeric, 1)    AS value
FROM employee_score e
LEFT JOIN departments d ON d.id = e.department_id
WHERE e.department_id IS NOT NULL
GROUP BY d.name

UNION ALL

SELECT 'age_band' AS bucket_type,
       e.age_band AS label,
       ROUND(AVG(e.metric_score)::numeric, 1) AS value
FROM employee_score e
WHERE e.age_band IS NOT NULL AND e.age_band <> ''
GROUP BY e.age_band
"""


# Returns the metric_code rows (one per active mapped metric) for the
# /definitions endpoint, scoped to the caller's company.
_DEFINITIONS_SQL = """
SELECT DISTINCT m.metric_code, m.display_name
FROM cxo_metric_master m
JOIN cxo_metric_kpi_mapping map
  ON map.metric_id = m.id
 AND map.company_id = m.company_id
 AND map.is_active AND NOT map.is_deleted
WHERE m.company_id = :company_id
  AND m.is_active   AND NOT m.is_deleted
ORDER BY m.metric_code
"""


class HrCxoMetricsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def fetch_metric(
        self,
        *,
        metric: str,
        company_id: UUID,
        filters: Optional[HrFilters] = None,
    ) -> dict:
        """Aggregate the CXO metric for the company.

        Raises BusinessException(404) if the metric has no active mapping
        configured for this company.

        ``filters`` narrows the employee pool on the seven shared HR
        Analytics axes (dept/loc/age/gender/date/theme). When a date
        window is set, the view-bypassing _AGGREGATE_DATE_SQL is used so
        "latest within window" semantics line up.
        """
        filters = filters or HrFilters()
        # 1. Mapping must exist. We check this explicitly so we can give a
        #    clean 404 rather than an empty buckets response.
        mapping_check = await self.db.execute(
            sql_text(
                "SELECT 1 FROM cxo_metric_kpi_mapping map "
                "JOIN cxo_metric_master m ON m.id = map.metric_id "
                "WHERE m.company_id = :company_id "
                "  AND UPPER(m.metric_code) = UPPER(:metric_code) "
                "  AND m.is_active AND NOT m.is_deleted "
                "  AND map.is_active AND NOT map.is_deleted "
                "LIMIT 1"
            ),
            {"company_id": company_id, "metric_code": metric},
        )
        if mapping_check.scalar() is None:
            raise BusinessException(
                message="CXO metric not configured", status_code=404
            )
        # 2. Single round-trip for both breakdowns.
        sql = (
            _AGGREGATE_DATE_SQL
            if filters.has_date_window()
            else _AGGREGATE_SQL
        )
        result = await self.db.execute(
            sql_text(sql),
            {
                "company_id": company_id,
                "metric_code": metric,
                **filters.bind_values(),
            },
        )
        rows = result.all()

        by_department: list[dict] = []
        by_age_band: list[dict] = []
        for bucket_type, label, value in rows:
            bucket = {
                "label": label or "",
                "value": Decimal(str(value)) if value is not None else Decimal("0"),
            }
            if bucket_type == "dept":
                by_department.append(bucket)
            else:
                by_age_band.append(bucket)

        by_department.sort(key=lambda b: b["label"])
        by_age_band.sort(key=lambda b: _age_band_sort_key(b["label"]))

        return {
            "metric": metric,
            "by_department": by_department,
            "by_age_band": by_age_band,
        }

    async def list_definitions(self, *, company_id: UUID) -> list[dict]:
        """Return the metrics that have at least one active mapping for the
        caller's company. `key` is lowercased to match the wire format the
        frontend toggles expect."""
        result = await self.db.execute(
            sql_text(_DEFINITIONS_SQL), {"company_id": company_id}
        )
        rows = result.all()
        return [
            {"key": metric_code.lower(), "label": display_name}
            for metric_code, display_name in rows
        ]


