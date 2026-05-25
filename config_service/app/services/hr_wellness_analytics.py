"""Service backing the HR wellness analytics endpoints.

Three feeds powering the HR Analytics dashboard's "Wellness by Dimension" and
"Gender-wise" charts:

  1. list_dimension_toggles()       — toggle buttons above the chart
  2. wellness_by_dimension(...)     — bars grouped by department and location
  3. gender_wellness_productivity() — horizontal bars by gender

"Latest submission per user" is sourced from `employee_form_response.is_latest
= TRUE` — the same flag that backs `v_user_kpi_score` and
`v_user_wellness_index`. We deliberately reuse those views so the freshness
semantics line up with the rest of the platform (CXO metrics, employee
snapshots, dashboards). Result: no per-endpoint ROW_NUMBER, and consistent
"latest" semantics across all three endpoints.

Schema notes (carried over from cxo_metrics_up.sql):
  * `company_users` has no `location_id`. Location is on `companies`, so every
    employee in a single-location company shares one bucket — by_location
    therefore degenerates to a single entry. Documented limitation, not a
    bug.
  * `kpis.display_name` is the join key against the dimension key (case-
    insensitive trimmed) — same fragile lookup the employee-snapshots feed
    uses. Flagged as schema issue #2 in cxo_metrics_up.sql.
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException


# Fixed display order for the gender chart. Genders missing from the data set
# are simply omitted (per spec).
_GENDER_ORDER: tuple[str, ...] = ("Male", "Female", "Other")


WELLNESS_INDEX_KEY = "wellnessindex"


# Standard working days per month — used to convert the absenteeism percentage
# into days for the summary card.
_WORKING_DAYS_PER_MONTH = Decimal("22")


# ---------------------------------------------------------------------------
# SQL fragments. `is_latest = TRUE` is implicit in the views, so callers don't
# need to repeat it.
# ---------------------------------------------------------------------------


# wellnessindex branch — average pre-computed wellness_index by dept / loc.
_WI_BY_BUCKET_SQL = """
WITH employees AS (
    SELECT
        cu.id          AS user_id,
        cu.department_id,
        c.location_id  AS location_id
    FROM company_users cu
    JOIN companies c ON c.id = cu.company_id
    WHERE cu.company_id = :company_id
      AND cu.is_active   = TRUE
      AND cu.is_deleted  = FALSE
)
SELECT
    'dept' AS bucket_type,
    COALESCE(d.name, '')                       AS label,
    ROUND(AVG(wi.wellness_index)::numeric, 1)  AS value
FROM employees e
JOIN v_user_wellness_index wi ON wi.user_id = e.user_id
LEFT JOIN departments d ON d.id = e.department_id
WHERE e.department_id IS NOT NULL
GROUP BY d.name

UNION ALL

SELECT
    'loc' AS bucket_type,
    COALESCE(l.name, '')                       AS label,
    ROUND(AVG(wi.wellness_index)::numeric, 1)  AS value
FROM employees e
JOIN v_user_wellness_index wi ON wi.user_id = e.user_id
LEFT JOIN locations l ON l.id = e.location_id
WHERE e.location_id IS NOT NULL
GROUP BY l.name
"""


# Configured dimension branch — pull raw (user, kpi, score) rows for the
# mapped KPIs. Aggregation happens in Python so the spec's "skip user if
# missing any mapped KPI" rule is enforced explicitly.
_DIMENSION_RAW_ROWS_SQL = """
WITH mapping AS (
    SELECT wdkm.kpi_key, wdkm.weight
    FROM wellness_dimension_kpi_mapping wdkm
    JOIN wellness_dimension wd ON wd.id = wdkm.dimension_id
    WHERE wd.dimension_key = :dimension_key
      AND wd.company_id    = :company_id
      AND wd.is_active     = TRUE
      AND wd.is_deleted    = FALSE
      AND wdkm.company_id  = :company_id
      AND wdkm.is_active   = TRUE
      AND wdkm.is_deleted  = FALSE
)
SELECT
    v.user_id      AS user_id,
    v.kpi_key      AS kpi_key,
    v.score        AS score,
    m.weight       AS weight,
    d.name         AS dept,
    l.name         AS loc
FROM v_user_kpi_score v
JOIN mapping m         ON m.kpi_key = v.kpi_key
JOIN company_users cu  ON cu.id      = v.user_id
                       AND cu.is_active  = TRUE
                       AND cu.is_deleted = FALSE
JOIN companies c       ON c.id       = cu.company_id
LEFT JOIN departments d ON d.id      = cu.department_id
LEFT JOIN locations  l ON l.id      = c.location_id
WHERE v.company_id = :company_id
"""


# Mapping existence check — used to return a clean 404 for unconfigured
# dimensions and to detect whether 'productivity' is configured for the
# gender-wellness endpoint.
_MAPPING_EXISTS_SQL = """
SELECT 1
FROM wellness_dimension_kpi_mapping wdkm
JOIN wellness_dimension wd ON wd.id = wdkm.dimension_id
WHERE wd.dimension_key = :dimension_key
  AND wd.company_id    = :company_id
  AND wd.is_active     = TRUE
  AND wd.is_deleted    = FALSE
  AND wdkm.company_id  = :company_id
  AND wdkm.is_active   = TRUE
  AND wdkm.is_deleted  = FALSE
LIMIT 1
"""


_DIMENSIONS_TOGGLES_SQL = """
SELECT id, dimension_key, dimension_label, display_order
FROM wellness_dimension
WHERE company_id = :company_id
  AND is_active  = TRUE
  AND is_deleted = FALSE
ORDER BY display_order ASC, id ASC
"""


# Gender wellness branch — average wellness_index by company_users.gender.
_GENDER_WELLNESS_SQL = """
SELECT
    cu.gender                                  AS gender,
    ROUND(AVG(wi.wellness_index)::numeric, 1)  AS value
FROM company_users cu
JOIN v_user_wellness_index wi ON wi.user_id = cu.id
WHERE cu.company_id  = :company_id
  AND cu.is_active   = TRUE
  AND cu.is_deleted  = FALSE
  AND cu.gender IS NOT NULL
  AND cu.gender <> ''
GROUP BY cu.gender
"""


# Location x Department heatmap — average wellness_index per (loc, dept) cell.
# Uses v_user_wellness_index (is_latest = TRUE baked in) so freshness aligns
# with the other HR analytics endpoints. Optional :department / :location
# filters are no-ops when bound as NULL — the explicit `::text` casts keep the
# driver from raising "could not determine data type of parameter" on a NULL
# bind.
_HEATMAP_LOC_DEPT_SQL = """
WITH employees AS (
    SELECT
        cu.id          AS user_id,
        cu.department_id,
        c.location_id  AS location_id
    FROM company_users cu
    JOIN companies c ON c.id = cu.company_id
    WHERE cu.company_id = :company_id
      AND cu.is_active   = TRUE
      AND cu.is_deleted  = FALSE
      AND cu.department_id IS NOT NULL
      AND c.location_id  IS NOT NULL
)
SELECT
    l.name                                     AS location,
    d.name                                     AS department,
    ROUND(AVG(wi.wellness_index)::numeric, 0)  AS value
FROM employees e
JOIN v_user_wellness_index wi ON wi.user_id = e.user_id
JOIN departments d            ON d.id = e.department_id
JOIN locations   l            ON l.id = e.location_id
WHERE (CAST(:department_filter AS TEXT) IS NULL OR d.name = CAST(:department_filter AS TEXT))
  AND (CAST(:location_filter   AS TEXT) IS NULL OR l.name = CAST(:location_filter   AS TEXT))
GROUP BY l.name, d.name
"""


# Date-filtered branch — the view bakes in `is_latest = TRUE`, which is wrong
# when a date window is supplied because "latest within window" may not be the
# globally-latest submission. So we recompute the WI inline using the same
# formula as v_user_wellness_index (((Σ score*weight / Σ weight) - 1)/4 * 100),
# but with the latest-per-user resolved against the date window.
_HEATMAP_LOC_DEPT_DATE_SQL = """
WITH employees AS (
    SELECT
        cu.id          AS user_id,
        cu.email       AS email,
        cu.company_id  AS company_id,
        cu.department_id,
        c.location_id  AS location_id
    FROM company_users cu
    JOIN companies c ON c.id = cu.company_id
    WHERE cu.company_id = :company_id
      AND cu.is_active   = TRUE
      AND cu.is_deleted  = FALSE
      AND cu.department_id IS NOT NULL
      AND c.location_id  IS NOT NULL
),
latest_response AS (
    SELECT DISTINCT ON (efr.employee_email)
        efr.employee_email,
        efr.response_id
    FROM employee_form_response efr
    JOIN employees e ON e.email = efr.employee_email
    WHERE efr.is_deleted     = FALSE
      AND efr.company_id::uuid = :company_id
      AND (CAST(:date_from AS DATE) IS NULL OR efr.submitted_at >= CAST(:date_from AS DATE))
      AND (CAST(:date_to   AS DATE) IS NULL OR efr.submitted_at <  CAST(:date_to   AS DATE) + INTERVAL '1 day')
    ORDER BY efr.employee_email, efr.submitted_at DESC
),
user_kpi_score AS (
    SELECT
        e.user_id,
        e.location_id,
        e.department_id,
        q.kpi                              AS kpi_key,
        AVG(efa.score)::numeric            AS score
    FROM employees e
    JOIN latest_response lr        ON lr.employee_email = e.email
    JOIN employee_form_answer efa  ON efa.response_id   = lr.response_id
                                  AND efa.is_deleted    = FALSE
    JOIN kpi_questions q           ON q.question_code   = efa.question_code
                                  AND q.company_id      = e.company_id
                                  AND q.is_deleted      = FALSE
    GROUP BY e.user_id, e.location_id, e.department_id, q.kpi
),
user_wi AS (
    SELECT
        uks.user_id,
        uks.location_id,
        uks.department_id,
        LEAST(100, GREATEST(0,
            ((SUM(uks.score * COALESCE(k.wi_weight, 0.10))
              / NULLIF(SUM(COALESCE(k.wi_weight, 0.10)), 0)) - 1) / 4 * 100
        )) AS wellness_index
    FROM user_kpi_score uks
    JOIN kpis k ON k.kpi_key    = uks.kpi_key
               AND k.company_id = :company_id
               AND k.is_active  = TRUE
               AND k.is_deleted = FALSE
    GROUP BY uks.user_id, uks.location_id, uks.department_id
)
SELECT
    l.name                                     AS location,
    d.name                                     AS department,
    ROUND(AVG(uw.wellness_index)::numeric, 0)  AS value
FROM user_wi uw
JOIN departments d ON d.id = uw.department_id
JOIN locations   l ON l.id = uw.location_id
WHERE (CAST(:department_filter AS TEXT) IS NULL OR d.name = CAST(:department_filter AS TEXT))
  AND (CAST(:location_filter   AS TEXT) IS NULL OR l.name = CAST(:location_filter   AS TEXT))
GROUP BY l.name, d.name
"""


# Summary-cards branch — per-user, per-KPI raw scores (1-5) for every employee
# in the company. Shared by all six cards: wellness index uses kpis.wi_weight,
# productivity / engagement / absenteeism use the wellness_dimension mapping
# (normalized to 0-100), and sleep / stress read the raw scores directly.
# Sourced from v_user_kpi_score so `is_latest = TRUE` is implicit.
_SUMMARY_USER_KPI_SCORES_SQL = """
SELECT v.user_id, v.kpi_key, v.score
FROM v_user_kpi_score v
WHERE v.company_id = :company_id
"""


# Date-filtered variant — bypasses the view's `is_latest = TRUE` flag because
# "latest within window" may not be the globally-latest submission. Recomputes
# the per-user KPI score (AVG over efa.score for the latest response within
# the date range) using the same join shape as v_user_kpi_score.
_SUMMARY_USER_KPI_SCORES_DATE_SQL = """
WITH employees AS (
    SELECT cu.id          AS user_id,
           cu.email        AS email,
           cu.company_id   AS company_id
    FROM company_users cu
    WHERE cu.company_id = :company_id
      AND cu.is_active   = TRUE
      AND cu.is_deleted  = FALSE
),
latest_response AS (
    SELECT DISTINCT ON (efr.employee_email)
        efr.employee_email,
        efr.response_id
    FROM employee_form_response efr
    JOIN employees e ON e.email = efr.employee_email
    WHERE efr.is_deleted       = FALSE
      AND efr.company_id::uuid = :company_id
      AND (CAST(:date_from AS DATE) IS NULL OR efr.submitted_at >= CAST(:date_from AS DATE))
      AND (CAST(:date_to   AS DATE) IS NULL OR efr.submitted_at <  CAST(:date_to   AS DATE) + INTERVAL '1 day')
    ORDER BY efr.employee_email, efr.submitted_at DESC
)
SELECT
    e.user_id,
    q.kpi                    AS kpi_key,
    AVG(efa.score)::numeric  AS score
FROM employees e
JOIN latest_response lr        ON lr.employee_email = e.email
JOIN employee_form_answer efa  ON efa.response_id   = lr.response_id
                              AND efa.is_deleted    = FALSE
JOIN kpi_questions q           ON q.question_code   = efa.question_code
                              AND q.company_id      = e.company_id
                              AND q.is_deleted      = FALSE
GROUP BY e.user_id, q.kpi
"""


# wi_weight per KPI — fed into the wellness-index formula in Python. Defaults
# to 0.10 to match the view's `COALESCE(k.wi_weight, 0.10)`.
_SUMMARY_KPI_WEIGHTS_SQL = """
SELECT kpi_key, COALESCE(wi_weight, 0.10) AS wi_weight
FROM kpis
WHERE company_id = :company_id
  AND is_active  = TRUE
  AND is_deleted = FALSE
"""


# Bulk dimension lookup — pulls the (kpi_key, weight) mapping for all five
# dimensions used by the summary cards in one round-trip. Keys are literal
# string constants, not user input, so inlining them is safe.
_SUMMARY_DIMENSION_MAPPINGS_SQL = """
SELECT LOWER(wd.dimension_key) AS dimension_key,
       wdkm.kpi_key             AS kpi_key,
       wdkm.weight              AS weight
FROM wellness_dimension_kpi_mapping wdkm
JOIN wellness_dimension wd ON wd.id = wdkm.dimension_id
WHERE wd.company_id   = :company_id
  AND wd.is_active    = TRUE
  AND wd.is_deleted   = FALSE
  AND wdkm.company_id = :company_id
  AND wdkm.is_active  = TRUE
  AND wdkm.is_deleted = FALSE
  AND LOWER(wd.dimension_key) IN ('productivity','engagement','absenteeism','sleep','stress')
"""


# Gender productivity branch — raw rows joined with the productivity mapping.
# Same shape as _DIMENSION_RAW_ROWS_SQL but with gender instead of dept/loc.
_GENDER_PRODUCTIVITY_RAW_SQL = """
WITH mapping AS (
    SELECT wdkm.kpi_key, wdkm.weight
    FROM wellness_dimension_kpi_mapping wdkm
    JOIN wellness_dimension wd ON wd.id = wdkm.dimension_id
    WHERE wd.dimension_key = 'productivity'
      AND wd.company_id    = :company_id
      AND wd.is_active     = TRUE
      AND wd.is_deleted    = FALSE
      AND wdkm.company_id  = :company_id
      AND wdkm.is_active   = TRUE
      AND wdkm.is_deleted  = FALSE
)
SELECT
    v.user_id  AS user_id,
    v.kpi_key  AS kpi_key,
    v.score    AS score,
    m.weight   AS weight,
    cu.gender  AS gender
FROM v_user_kpi_score v
JOIN mapping m         ON m.kpi_key = v.kpi_key
JOIN company_users cu  ON cu.id      = v.user_id
                       AND cu.is_active  = TRUE
                       AND cu.is_deleted = FALSE
WHERE v.company_id = :company_id
  AND cu.gender IS NOT NULL
  AND cu.gender <> ''
"""


def _normalize_score(raw_score: Decimal) -> Decimal:
    """Map the 1-5 form scale to 0-100. ((score - 1) / 4) * 100."""
    return (Decimal(raw_score) - Decimal("1")) / Decimal("4") * Decimal("100")


def _round1(value: Decimal) -> Decimal:
    """Round half-up to 1 decimal place, matching the rest of the project."""
    return value.quantize(Decimal("0.1"))


class HrWellnessAnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -----------------------------------------------------------------------
    # Endpoint 1 — toggle definitions
    # -----------------------------------------------------------------------

    async def list_dimension_toggles(self, *, company_id: UUID) -> list[dict]:
        """Returns the toggle list with WellnessIndex prepended at order=0.
        Dimensions are scoped to the caller's company."""
        rows = (
            await self.db.execute(
                sql_text(_DIMENSIONS_TOGGLES_SQL), {"company_id": company_id}
            )
        ).all()

        toggles: list[dict] = [
            {"key": WELLNESS_INDEX_KEY, "label": "WellnessIndex", "order": 0}
        ]
        for _id, dimension_key, dimension_label, display_order in rows:
            toggles.append(
                {
                    "key": dimension_key,
                    "label": dimension_label,
                    "order": int(display_order) if display_order is not None else 0,
                }
            )
        return toggles

    # -----------------------------------------------------------------------
    # Endpoint 2 — wellness by dimension
    # -----------------------------------------------------------------------

    async def wellness_by_dimension(
        self, *, dimension: str, company_id: UUID
    ) -> dict:
        """Branches on the dimension key — `wellnessindex` reads the
        pre-computed view; any other key reads the configured KPI mapping.
        Raises BusinessException(404) when the dimension is not configured."""
        key = (dimension or "").strip().lower()
        if key == WELLNESS_INDEX_KEY:
            buckets = await self._wellness_index_buckets(company_id=company_id)
        else:
            buckets = await self._configured_dimension_buckets(
                dimension_key=key, company_id=company_id
            )
        return {
            "dimension": key,
            "by_department": buckets["by_department"],
            "by_location": buckets["by_location"],
        }

    async def _wellness_index_buckets(self, *, company_id: UUID) -> dict:
        result = await self.db.execute(
            sql_text(_WI_BY_BUCKET_SQL), {"company_id": company_id}
        )
        by_department: list[dict] = []
        by_location: list[dict] = []
        for bucket_type, label, value in result.all():
            entry = {
                "label": label or "",
                "value": Decimal(str(value)) if value is not None else Decimal("0.0"),
            }
            if bucket_type == "dept":
                by_department.append(entry)
            else:
                by_location.append(entry)
        by_department.sort(key=lambda b: b["label"])
        by_location.sort(key=lambda b: b["label"])
        return {"by_department": by_department, "by_location": by_location}

    async def _configured_dimension_buckets(
        self, *, dimension_key: str, company_id: UUID
    ) -> dict:
        # 1. Verify the dimension is configured for this tenant. Empty -> 404.
        mapping_check = await self.db.execute(
            sql_text(_MAPPING_EXISTS_SQL),
            {"dimension_key": dimension_key, "company_id": company_id},
        )
        if mapping_check.scalar() is None:
            raise BusinessException(
                message=f"Dimension '{dimension_key}' is not configured",
                status_code=404,
            )

        # 2. Pull raw (user, kpi, score, weight, dept, loc) rows.
        rows = (
            await self.db.execute(
                sql_text(_DIMENSION_RAW_ROWS_SQL),
                {"dimension_key": dimension_key, "company_id": company_id},
            )
        ).all()

        # 3. Group rows by user_id; collect (kpi_key, score, weight) per user
        # plus the demographic fields (constant per user).
        per_user: dict = {}
        for user_id, kpi_key, score, weight, dept, loc in rows:
            entry = per_user.setdefault(
                user_id,
                {"dept": dept, "loc": loc, "kpis": {}},
            )
            entry["kpis"][kpi_key] = {
                "score": Decimal(str(score)),
                "weight": Decimal(str(weight)),
            }

        # 4. Mapping size — used to enforce "skip user if missing any KPI".
        mapping_size = (
            await self.db.execute(
                sql_text(
                    "SELECT COUNT(*) FROM wellness_dimension_kpi_mapping wdkm "
                    "JOIN wellness_dimension wd ON wd.id = wdkm.dimension_id "
                    "WHERE wd.dimension_key = :dimension_key "
                    "  AND wd.company_id = :company_id "
                    "  AND wd.is_active = TRUE AND wd.is_deleted = FALSE "
                    "  AND wdkm.company_id = :company_id "
                    "  AND wdkm.is_active = TRUE AND wdkm.is_deleted = FALSE"
                ),
                {"dimension_key": dimension_key, "company_id": company_id},
            )
        ).scalar_one()
        mapping_size = int(mapping_size)

        # 5. Compute per-employee weighted score, then bucket aggregates.
        dept_accum: dict[str, list[Decimal]] = {}
        loc_accum: dict[str, list[Decimal]] = {}
        for entry in per_user.values():
            if len(entry["kpis"]) < mapping_size:
                # User is missing one or more mapped KPIs — skip per spec.
                continue
            num = Decimal("0")
            denom = Decimal("0")
            for kpi in entry["kpis"].values():
                normalized = _normalize_score(kpi["score"])
                num += normalized * kpi["weight"]
                denom += kpi["weight"]
            if denom == 0:
                continue
            employee_score = num / denom
            if entry["dept"]:
                dept_accum.setdefault(entry["dept"], []).append(employee_score)
            if entry["loc"]:
                loc_accum.setdefault(entry["loc"], []).append(employee_score)

        by_department = [
            {
                "label": label,
                "value": _round1(sum(values) / Decimal(len(values))),
            }
            for label, values in sorted(dept_accum.items())
        ]
        by_location = [
            {
                "label": label,
                "value": _round1(sum(values) / Decimal(len(values))),
            }
            for label, values in sorted(loc_accum.items())
        ]
        return {"by_department": by_department, "by_location": by_location}

    # -----------------------------------------------------------------------
    # Endpoint 3 — gender wellness + productivity
    # -----------------------------------------------------------------------

    async def gender_wellness_productivity(
        self, *, company_id: UUID
    ) -> list[dict]:
        """Wellness comes from `v_user_wellness_index`; productivity from the
        configured `productivity` dimension mapping. Missing dimension
        configuration returns `productivity_score=None` (per spec, not an
        error). Genders with no wellness data are omitted from the response."""
        wellness_rows = (
            await self.db.execute(
                sql_text(_GENDER_WELLNESS_SQL), {"company_id": company_id}
            )
        ).all()
        wellness_by_gender: dict[str, Decimal] = {
            (gender or "").strip(): Decimal(str(value))
            for gender, value in wellness_rows
            if value is not None
        }

        productivity_by_gender = await self._productivity_by_gender(
            company_id=company_id
        )

        result: list[dict] = []
        for canonical in _GENDER_ORDER:
            wellness = wellness_by_gender.get(canonical)
            if wellness is None:
                # Some datasets store gender lowercased — accept that too.
                wellness = wellness_by_gender.get(canonical.lower())
            if wellness is None:
                continue
            productivity = productivity_by_gender.get(canonical)
            if productivity is None:
                productivity = productivity_by_gender.get(canonical.lower())
            result.append(
                {
                    "gender": canonical,
                    "wellness_score": _round1(wellness),
                    "productivity_score": (
                        _round1(productivity) if productivity is not None else None
                    ),
                }
            )
        return result

    async def _productivity_by_gender(
        self, *, company_id: UUID
    ) -> dict[str, Optional[Decimal]]:
        """Returns {gender: avg(weighted_productivity)} or an empty dict when
        the 'productivity' dimension isn't configured for this tenant."""
        mapping_check = await self.db.execute(
            sql_text(_MAPPING_EXISTS_SQL),
            {"dimension_key": "productivity", "company_id": company_id},
        )
        if mapping_check.scalar() is None:
            return {}

        rows = (
            await self.db.execute(
                sql_text(_GENDER_PRODUCTIVITY_RAW_SQL), {"company_id": company_id}
            )
        ).all()

        per_user: dict = {}
        for user_id, kpi_key, score, weight, gender in rows:
            entry = per_user.setdefault(
                user_id, {"gender": (gender or "").strip(), "kpis": {}}
            )
            entry["kpis"][kpi_key] = {
                "score": Decimal(str(score)),
                "weight": Decimal(str(weight)),
            }

        mapping_size = (
            await self.db.execute(
                sql_text(
                    "SELECT COUNT(*) FROM wellness_dimension_kpi_mapping wdkm "
                    "JOIN wellness_dimension wd ON wd.id = wdkm.dimension_id "
                    "WHERE wd.dimension_key = 'productivity' "
                    "  AND wd.company_id = :company_id "
                    "  AND wd.is_active = TRUE AND wd.is_deleted = FALSE "
                    "  AND wdkm.company_id = :company_id "
                    "  AND wdkm.is_active = TRUE AND wdkm.is_deleted = FALSE"
                ),
                {"company_id": company_id},
            )
        ).scalar_one()
        mapping_size = int(mapping_size)

        accum: dict[str, list[Decimal]] = {}
        for entry in per_user.values():
            if len(entry["kpis"]) < mapping_size:
                continue
            num = Decimal("0")
            denom = Decimal("0")
            for kpi in entry["kpis"].values():
                normalized = _normalize_score(kpi["score"])
                num += normalized * kpi["weight"]
                denom += kpi["weight"]
            if denom == 0:
                continue
            employee_score = num / denom
            if entry["gender"]:
                accum.setdefault(entry["gender"], []).append(employee_score)

        return {
            label: (sum(values) / Decimal(len(values))) if values else None
            for label, values in accum.items()
        }

    # -----------------------------------------------------------------------
    # Endpoint 4 — Location x Department wellness heatmap
    # -----------------------------------------------------------------------

    async def wellness_heatmap_location_department(
        self,
        *,
        company_id: UUID,
        department: Optional[str] = None,
        location: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> dict:
        """Aggregates wellness_index by (location, department). Returns the
        nested heatmap structure the frontend renders directly — a sorted
        `locations` list, a sorted `departments` list, and a `heatmap` array
        with one row per location whose `scores` cover every department
        (value=null at empty intersections).

        Date filters bypass `v_user_wellness_index` (whose `is_latest = TRUE`
        flag is wrong inside a date window) and recompute the WI inline using
        the latest submission within the window."""
        use_date_branch = date_from is not None or date_to is not None
        params = {
            "company_id": company_id,
            "department_filter": department or None,
            "location_filter": location or None,
        }
        if use_date_branch:
            params["date_from"] = date_from
            params["date_to"] = date_to
            sql = _HEATMAP_LOC_DEPT_DATE_SQL
        else:
            sql = _HEATMAP_LOC_DEPT_SQL

        rows = (await self.db.execute(sql_text(sql), params)).all()

        # Empty result → return the documented empty shape (not an error).
        if not rows:
            return {"locations": [], "departments": [], "heatmap": []}

        # Group cell values by (location, department). DB returned at most one
        # row per pair, but use a dict for shape clarity.
        cell_lookup: dict[tuple[str, str], Optional[Decimal]] = {}
        locations_seen: set[str] = set()
        departments_seen: set[str] = set()
        for loc_label, dept_label, value in rows:
            if not loc_label or not dept_label:
                continue
            locations_seen.add(loc_label)
            departments_seen.add(dept_label)
            cell_lookup[(loc_label, dept_label)] = (
                Decimal(str(value)) if value is not None else None
            )

        if not locations_seen or not departments_seen:
            return {"locations": [], "departments": [], "heatmap": []}

        locations_sorted = sorted(locations_seen)
        departments_sorted = sorted(departments_seen)

        heatmap: list[dict] = []
        for loc_label in locations_sorted:
            heatmap.append(
                {
                    "location": loc_label,
                    "scores": [
                        {
                            "department": dept_label,
                            "value": cell_lookup.get((loc_label, dept_label)),
                        }
                        for dept_label in departments_sorted
                    ],
                }
            )

        return {
            "locations": locations_sorted,
            "departments": departments_sorted,
            "heatmap": heatmap,
        }

    # -----------------------------------------------------------------------
    # Endpoint 5 — HR Analytics summary cards
    # -----------------------------------------------------------------------

    async def summary_cards(
        self,
        *,
        company_id: UUID,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> dict:
        """Builds the six summary cards in a single pass.

        Shared base data (one query):
          per_user[user_id][kpi_key] = raw 1-5 average score on the latest
          submission for that user (globally-latest, or latest within the
          date window when filters are supplied).

        From this base, derives:
          * Card 1 (avg wellness) — re-computes the v_user_wellness_index
            formula in Python, clamping to [0, 100] per user before averaging.
          * Cards 2/3 (productivity, engagement) — weighted dimension score
            normalized to 0-100, skipping users missing any mapped KPI, then
            averaged across remaining users.
          * Card 4 (absenteeism) — same as 2/3 then `100 - score` converted to
            days via the standard 22-day working month.
          * Cards 5/6 (sleep, stress) — raw 1-5 score averaged across KPIs
            mapped to the dimension, then averaged across users. Stress is
            display-inverted to `6 - avg` per spec so a lower card value
            means more stress (matching the "lower is better" subtext).

        Dimensions with no mapping return `value=None` on their card. An empty
        employee pool returns `value=None` on every card."""
        use_date_branch = date_from is not None or date_to is not None
        base_params: dict = {"company_id": company_id}
        if use_date_branch:
            base_params["date_from"] = date_from
            base_params["date_to"] = date_to
            kpi_sql = _SUMMARY_USER_KPI_SCORES_DATE_SQL
        else:
            kpi_sql = _SUMMARY_USER_KPI_SCORES_SQL

        # 1. Per-user (kpi_key -> score) — the shared base for every card.
        kpi_rows = (
            await self.db.execute(sql_text(kpi_sql), base_params)
        ).all()
        per_user: dict = {}
        for user_id, kpi_key, score in kpi_rows:
            per_user.setdefault(user_id, {})[kpi_key] = Decimal(str(score))

        # 2. wi_weight per KPI for the wellness-index recomputation.
        wi_rows = (
            await self.db.execute(
                sql_text(_SUMMARY_KPI_WEIGHTS_SQL), {"company_id": company_id}
            )
        ).all()
        wi_weights: dict = {
            kpi_key: Decimal(str(w)) for kpi_key, w in wi_rows
        }

        # 3. Mapping (kpi_key, weight) for the five dimensions, one round-trip.
        dim_rows = (
            await self.db.execute(
                sql_text(_SUMMARY_DIMENSION_MAPPINGS_SQL),
                {"company_id": company_id},
            )
        ).all()
        mappings: dict[str, list[tuple]] = {}
        for dim_key, kpi_key, weight in dim_rows:
            mappings.setdefault(dim_key, []).append(
                (kpi_key, Decimal(str(weight)))
            )

        # 4. Compose card values.
        avg_wellness = self._cards_avg_wellness_index(per_user, wi_weights)
        productivity = self._cards_weighted_dim_avg(
            per_user, mappings.get("productivity")
        )
        engagement = self._cards_weighted_dim_avg(
            per_user, mappings.get("engagement")
        )
        absenteeism_dim_score = self._cards_weighted_dim_avg(
            per_user, mappings.get("absenteeism")
        )
        absenteeism_days: Optional[Decimal]
        if absenteeism_dim_score is None:
            absenteeism_days = None
        else:
            absenteeism_pct = Decimal("100") - absenteeism_dim_score
            absenteeism_days = _round1(
                (absenteeism_pct / Decimal("100")) * _WORKING_DAYS_PER_MONTH
            )

        sleep_score = self._cards_raw_kpi_avg(per_user, mappings.get("sleep"))
        stress_raw = self._cards_raw_kpi_avg(per_user, mappings.get("stress"))
        # Spec: `displayed_stress = 6 - average_score` so a low card value
        # reads as "more stress" alongside the "lower is better" subtext.
        stress_score = (
            _round1(Decimal("6") - stress_raw) if stress_raw is not None else None
        )

        return {
            "avg_wellness": {
                "value": avg_wellness,
                "unit": "/100",
                "label": "Avg Wellness",
                "subtext": None,
            },
            "productivity": {
                "value": productivity,
                "unit": "%",
                "label": "Productivity",
                "subtext": "self-reported",
            },
            "engagement": {
                "value": engagement,
                "unit": "%",
                "label": "Engagement",
                "subtext": "Gallup Q12",
            },
            "absenteeism": {
                "value": absenteeism_days,
                "unit": "d",
                "label": "Absenteeism",
                "subtext": "per month",
            },
            "sleep_score": {
                "value": sleep_score,
                "unit": "out of 5",
                "label": "Sleep Score",
                "subtext": None,
            },
            "stress_score": {
                "value": stress_score,
                "unit": "lower is better",
                "label": "Stress Score",
                "subtext": None,
            },
        }

    # ------- summary-cards helpers ---------------------------------------

    @staticmethod
    def _cards_avg_wellness_index(
        per_user: dict, wi_weights: dict
    ) -> Optional[Decimal]:
        """Re-applies v_user_wellness_index's formula in Python so the date-
        filtered branch can produce the same number without bypassing the
        same clamping logic the view uses."""
        if not per_user or not wi_weights:
            return None
        per_user_wi: list[Decimal] = []
        for kpi_scores in per_user.values():
            num = Decimal("0")
            denom = Decimal("0")
            for kpi_key, score in kpi_scores.items():
                w = wi_weights.get(kpi_key)
                if w is None:
                    continue
                num += score * w
                denom += w
            if denom == 0:
                continue
            wi = ((num / denom) - Decimal("1")) / Decimal("4") * Decimal("100")
            if wi < 0:
                wi = Decimal("0")
            elif wi > 100:
                wi = Decimal("100")
            per_user_wi.append(wi)
        if not per_user_wi:
            return None
        return _round1(sum(per_user_wi) / Decimal(len(per_user_wi)))

    @staticmethod
    def _cards_weighted_dim_avg(
        per_user: dict, mapping: Optional[list[tuple]]
    ) -> Optional[Decimal]:
        """Same per-user weighted-dimension semantics as
        `_configured_dimension_buckets`: normalize each KPI to 0-100, weight
        by `wellness_dimension_kpi_mapping.weight`, skip users missing any
        mapped KPI, then plain-average across remaining users."""
        if not mapping:
            return None
        mapping_kpis = [kpi_key for kpi_key, _ in mapping]
        per_user_scores: list[Decimal] = []
        for kpi_scores in per_user.values():
            if any(kpi_key not in kpi_scores for kpi_key in mapping_kpis):
                continue
            num = Decimal("0")
            denom = Decimal("0")
            for kpi_key, weight in mapping:
                normalized = _normalize_score(kpi_scores[kpi_key])
                num += normalized * weight
                denom += weight
            if denom == 0:
                continue
            per_user_scores.append(num / denom)
        if not per_user_scores:
            return None
        return _round1(
            sum(per_user_scores) / Decimal(len(per_user_scores))
        )

    @staticmethod
    def _cards_raw_kpi_avg(
        per_user: dict, mapping: Optional[list[tuple]]
    ) -> Optional[Decimal]:
        """Plain raw 1-5 average across the KPIs mapped to the dimension. For
        each user we average the mapped KPIs they actually answered (no
        skip-on-missing rule — sleep and stress cards keep partial data) and
        then average across users."""
        if not mapping:
            return None
        mapping_kpis = [kpi_key for kpi_key, _ in mapping]
        per_user_scores: list[Decimal] = []
        for kpi_scores in per_user.values():
            answered = [kpi_scores[k] for k in mapping_kpis if k in kpi_scores]
            if not answered:
                continue
            per_user_scores.append(sum(answered) / Decimal(len(answered)))
        if not per_user_scores:
            return None
        return _round1(
            sum(per_user_scores) / Decimal(len(per_user_scores))
        )
