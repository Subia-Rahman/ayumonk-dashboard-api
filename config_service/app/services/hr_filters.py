from __future__ import annotations
"""Shared filter helpers for the HR Analytics endpoints.

Every chart on the HR Analytics dashboard shares one filter panel —
Department, Location, Age Band, Gender, Date Range, Theme/Program — and
the spec calls for every endpoint to narrow on the same axes. This module
holds the shared dataclass, FastAPI dependency, and SQL fragment builders
so each service can splice the same filter logic into its existing
employee CTE without restating the seven WHERE clauses every time.

Alias contract for the SQL fragments:
  * ``cu``  — ``company_users``
  * ``c``   — ``companies``                       (for location_id chain)
  * ``d``   — ``departments``  LEFT JOIN cu.department_id
  * ``l``   — ``locations``    LEFT JOIN c.location_id
  * ``efr`` — ``employee_form_response``          (only required by
              ``SUBMISSION_WINDOW_SQL`` — fragment is omitted entirely
              when the caller has no submission scope.)

Bind names are prefixed with ``f_`` so they cannot clash with the
endpoint's own bound params (``company_id`` / ``dimension_key`` / etc).
``HrFilters.bind_values()`` is safe to merge with the caller's params
dict without overwriting anything.

Open-question resolutions baked in here (see plan):
  1. ``gender`` filter is *applicable only* to non-gender-grouping
     endpoints. ``EMPLOYEE_DEMOGRAPHIC_FILTERS_NO_GENDER_SQL`` is the
     variant used by ``/hr/gender-wellness`` (degenerate otherwise).
  2. ``theme_key`` semantics: employee qualifies if their latest
     submission scored at least one KPI belonging to the theme (works
     against today's schema; no ``company_themes`` dependency).
  3. Caching: deliberately none — these queries are sub-100ms.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import Query


# ---------------------------------------------------------------------------
# HrFilters dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HrFilters:
    """Frozen snapshot of the seven HR Analytics filter values.

    All fields are Optional — None means "do not narrow on this axis".
    Pass an instance through to the service layer and merge
    ``bind_values()`` into your existing SQL bind dict.
    """

    department: Optional[str] = None
    location: Optional[str] = None
    age_band: Optional[str] = None
    gender: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    theme_key: Optional[UUID] = None

    def has_date_window(self) -> bool:
        return self.date_from is not None or self.date_to is not None

    def bind_values(self) -> dict:
        """Bind values for ``sql_text(...).execute()``.

        Every name is always present (bound to None when unset) so the
        ``CAST(:f_x AS T) IS NULL`` no-op pattern in the SQL fragments
        works without the driver raising "could not determine data
        type" on a missing bind.
        """
        return {
            "f_department": self.department or None,
            "f_location": self.location or None,
            "f_age_band": self.age_band or None,
            "f_gender": self.gender or None,
            "f_date_from": self.date_from,
            "f_date_to": self.date_to,
            "f_theme_key": self.theme_key,
        }


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def hr_filters_from_query(
    department: Optional[str] = Query(
        default=None,
        description=(
            "Narrow to employees in this department (exact-name match)."
        ),
    ),
    location: Optional[str] = Query(
        default=None,
        description=(
            "Narrow to employees in companies at this location "
            "(exact-name match)."
        ),
    ),
    age_band: Optional[str] = Query(
        default=None,
        description=(
            "Narrow to employees in this age band. One of "
            "'20-25' / '26-30' / '31-35' / '36-40' / '41-50' / '50+'."
        ),
    ),
    gender: Optional[str] = Query(
        default=None,
        description=(
            "Narrow to employees with this gender. Ignored on "
            "/hr/gender-wellness (which already groups by gender)."
        ),
    ),
    date_from: Optional[date] = Query(
        default=None,
        description=(
            "Only submissions on or after this date qualify as the latest "
            "per employee. Applied as a per-submission window."
        ),
    ),
    date_to: Optional[date] = Query(
        default=None,
        description=(
            "Only submissions on or before this date qualify as the latest "
            "per employee."
        ),
    ),
    theme_key: Optional[UUID] = Query(
        default=None,
        description=(
            "Narrow to employees whose latest submission scored at least "
            "one KPI belonging to this theme. Works without "
            "company_themes — uses kpis.theme_key directly."
        ),
    ),
) -> HrFilters:
    """FastAPI ``Depends`` factory that reads the seven query params and
    returns an immutable ``HrFilters`` instance."""
    return HrFilters(
        department=department,
        location=location,
        age_band=age_band,
        gender=gender,
        date_from=date_from,
        date_to=date_to,
        theme_key=theme_key,
    )


# ---------------------------------------------------------------------------
# SQL fragment builders
# ---------------------------------------------------------------------------
#
# Each fragment is a chunk of SQL the caller AND-into their existing employee
# CTE's WHERE clause. The bind names match ``HrFilters.bind_values()``.
# ``CAST(:p AS T) IS NULL`` means "filter unset → fragment is a no-op" while
# keeping the driver happy on a NULL bind.

EMPLOYEE_DEMOGRAPHIC_FILTERS_SQL = """
  AND (CAST(:f_department AS TEXT) IS NULL OR d.name      = CAST(:f_department AS TEXT))
  AND (CAST(:f_location   AS TEXT) IS NULL OR l.name      = CAST(:f_location   AS TEXT))
  AND (CAST(:f_age_band   AS TEXT) IS NULL OR cu.age_band = CAST(:f_age_band   AS TEXT))
  AND (CAST(:f_gender     AS TEXT) IS NULL OR cu.gender   = CAST(:f_gender     AS TEXT))
"""


# Same fragment minus the gender clause — for endpoints that group by gender
# (``/hr/gender-wellness``). Filtering by the grouping axis would either nuke
# 2 of the 3 bars or be a no-op; either way, degenerate UX. Ignore it instead.
EMPLOYEE_DEMOGRAPHIC_FILTERS_NO_GENDER_SQL = """
  AND (CAST(:f_department AS TEXT) IS NULL OR d.name      = CAST(:f_department AS TEXT))
  AND (CAST(:f_location   AS TEXT) IS NULL OR l.name      = CAST(:f_location   AS TEXT))
  AND (CAST(:f_age_band   AS TEXT) IS NULL OR cu.age_band = CAST(:f_age_band   AS TEXT))
"""


# Submission window. Caller must have ``efr`` (employee_form_response) in
# scope. Apply inside the latest_response CTE so "latest within window"
# semantics line up with how the existing date-branch queries already work.
SUBMISSION_WINDOW_SQL = """
  AND (CAST(:f_date_from AS DATE) IS NULL OR efr.submitted_at >= CAST(:f_date_from AS DATE))
  AND (CAST(:f_date_to   AS DATE) IS NULL OR efr.submitted_at <  CAST(:f_date_to   AS DATE) + INTERVAL '1 day')
"""


# Theme scope — restrict employee pool to those whose company owns the
# requested theme. Themes are already company-scoped via themes.company_id,
# so the check is a simple membership EXISTS — no separate assignment
# table needed (theme time-boundation lives on KPIs and challenges, not
# at the theme level). EXISTS-correlated so it doesn't widen the row
# set. Caller must have ``cu`` in scope.
THEME_SCOPE_FILTER_SQL = """
  AND (
    CAST(:f_theme_key AS UUID) IS NULL
    OR EXISTS (
      SELECT 1
      FROM themes t_theme
      WHERE t_theme.theme_key   = CAST(:f_theme_key AS UUID)
        AND t_theme.company_id  = cu.company_id
        AND t_theme.is_active   = TRUE
        AND t_theme.is_deleted  = FALSE
    )
  )
"""
