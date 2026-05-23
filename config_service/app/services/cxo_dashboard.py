"""Service backing GET /api/v1/dashboard/cxo-by-dimension.

Reads from v_user_cxo (Productivity / Absenteeism) or invokes
compute_user_engagement() per user (Engagement). Applies k-anonymity at the
bucket level: any breakdown bucket below `K_ANONYMITY_FLOOR` is dropped
from the response and counted in `meta.suppressedBuckets`.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.config import APP_TZ


MetricCode = Literal["productivity", "engagement", "absenteeism"]
BreakdownCode = Literal["dept", "age_band"]

# Minimum cohort size for a bucket to appear in the dashboard response.
# Buckets below the floor are dropped and counted in `meta.suppressedBuckets`.
K_ANONYMITY_FLOOR = 5

# Canonical sort order for age bands. Buckets outside this set sort last,
# alphabetically.
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
    """Buckets inside CANONICAL_AGE_BANDS take their fixed rank; everything
    else gets `len(CANONICAL_AGE_BANDS)` and falls back to alphabetical
    ordering — placing them after the canonical buckets."""
    if label in _AGE_BAND_RANK:
        return (_AGE_BAND_RANK[label], "")
    return (len(CANONICAL_AGE_BANDS), label or "")


def _now_in_app_tz() -> datetime:
    return datetime.now(APP_TZ)


# ---------------------------------------------------------------------------
# Filter & cohort SQL — shared by productivity/absenteeism and engagement
# ---------------------------------------------------------------------------


def _cohort_clauses() -> str:
    """The WHERE clauses every cohort query shares. Bind params are
    company_id, department_id, age_band, gender."""
    return (
        "  cu.company_id = :company_id\n"
        "  AND cu.is_active = TRUE\n"
        "  AND cu.is_deleted = FALSE\n"
        "  AND (:department_id IS NULL OR cu.department_id = :department_id)\n"
        "  AND (:age_band      IS NULL OR cu.age_band      = :age_band)\n"
        "  AND (:gender        IS NULL OR cu.gender        = :gender)\n"
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def _productivity_query(*, breakdown: BreakdownCode) -> str:
    """Returns (label, value, cohort_size) rows for Productivity, grouped by
    department or age_band. K-anonymity is applied in Python using
    K_ANONYMITY_FLOOR."""
    if breakdown == "dept":
        label_col = "d.name"
        group_col = "v.department_id"
        join_clause = "LEFT JOIN departments d ON d.id = v.department_id"
    else:
        label_col = "v.age_band"
        group_col = "v.age_band"
        join_clause = ""

    return f"""
WITH cohort AS (
    SELECT cu.id AS user_id, cu.department_id, cu.age_band
    FROM company_users cu
    WHERE
    {_cohort_clauses()}
),
metric AS (
    SELECT v.user_id, v.department_id, v.age_band, v.productivity_pct AS value
    FROM v_user_cxo v
    JOIN cohort c ON c.user_id = v.user_id
    WHERE v.productivity_pct IS NOT NULL
)
SELECT
    {label_col}::text                AS label,
    ROUND(AVG(value), 1)             AS value,
    COUNT(*)                         AS cohort_size
FROM metric v
{join_clause}
GROUP BY {label_col}, {group_col}
"""


def _absenteeism_query(*, breakdown: BreakdownCode) -> str:
    if breakdown == "dept":
        label_col = "d.name"
        group_col = "v.department_id"
        join_clause = "LEFT JOIN departments d ON d.id = v.department_id"
    else:
        label_col = "v.age_band"
        group_col = "v.age_band"
        join_clause = ""

    return f"""
WITH cohort AS (
    SELECT cu.id AS user_id, cu.department_id, cu.age_band
    FROM company_users cu
    WHERE
    {_cohort_clauses()}
),
metric AS (
    SELECT v.user_id, v.department_id, v.age_band, v.absenteeism_days AS value
    FROM v_user_cxo v
    JOIN cohort c ON c.user_id = v.user_id
    WHERE v.absenteeism_days IS NOT NULL
)
SELECT
    {label_col}::text                AS label,
    ROUND(AVG(value), 1)             AS value,
    COUNT(*)                         AS cohort_size
FROM metric v
{join_clause}
GROUP BY {label_col}, {group_col}
"""


def _engagement_query(*, breakdown: BreakdownCode) -> str:
    """Engagement is computed per-user by the PL/pgSQL function. We invoke it
    inside a CTE so the entire calc happens in one roundtrip."""
    if breakdown == "dept":
        label_col = "d.name"
        group_col = "e.department_id"
        join_clause = "LEFT JOIN departments d ON d.id = e.department_id"
    else:
        label_col = "e.age_band"
        group_col = "e.age_band"
        join_clause = ""

    return f"""
WITH cohort AS (
    SELECT cu.id AS user_id, cu.department_id, cu.age_band
    FROM company_users cu
    WHERE
    {_cohort_clauses()}
),
engagement AS (
    SELECT c.user_id, c.department_id, c.age_band,
           compute_user_engagement(c.user_id) AS value
    FROM cohort c
)
SELECT
    {label_col}::text                AS label,
    ROUND(AVG(value), 1)             AS value,
    COUNT(*)                         AS cohort_size
FROM engagement e
{join_clause}
WHERE e.value IS NOT NULL
GROUP BY {label_col}, {group_col}
"""


_QUERY_BUILDERS = {
    "productivity": _productivity_query,
    "absenteeism": _absenteeism_query,
    "engagement": _engagement_query,
}


# ---------------------------------------------------------------------------
# Service entry point
# ---------------------------------------------------------------------------


class CxoByDimensionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def fetch(
        self,
        *,
        metric: MetricCode,
        breakdown: BreakdownCode,
        company_id: UUID,
        department_id: Optional[UUID],
        age_band: Optional[str],
        gender: Optional[str],
    ) -> dict:
        # Verify the company exists; the floor is a code-level constant.
        company_row = await self.db.execute(
            sql_text("SELECT 1 FROM companies WHERE id = :id"),
            {"id": company_id},
        )
        if company_row.scalar() is None:
            raise BusinessException(message="Company not found", status_code=404)
        floor = K_ANONYMITY_FLOOR

        builder = _QUERY_BUILDERS[metric]
        stmt = sql_text(builder(breakdown=breakdown))
        params = {
            "company_id": company_id,
            "department_id": department_id,
            "age_band": age_band,
            "gender": gender,
        }
        res = await self.db.execute(stmt, params)
        rows = res.all()

        # K-anonymity: drop buckets below floor.
        suppressed = 0
        buckets: list[dict] = []
        total_cohort = 0
        for row in rows:
            label = row[0] if row[0] is not None else ""
            value = row[1]
            cohort_size = int(row[2] or 0)
            total_cohort += cohort_size
            if cohort_size < floor:
                suppressed += 1
                continue
            buckets.append(
                {
                    "label": label,
                    "value": Decimal(str(value)) if value is not None else Decimal("0"),
                    "cohortSize": cohort_size,
                }
            )

        # Ordering: dept = alphabetical (Postgres sort already does this for
        # text), age_band = canonical-then-alphabetical.
        if breakdown == "age_band":
            buckets.sort(key=lambda b: _age_band_sort_key(b["label"]))
        else:
            buckets.sort(key=lambda b: b["label"])

        return {
            "data": buckets,
            "meta": {
                "metric": metric,
                "breakdown": breakdown,
                "cohortSize": total_cohort,
                "kAnonymityFloor": int(floor),
                "updatedAt": _now_in_app_tz(),
                "suppressedBuckets": suppressed,
            },
        }
