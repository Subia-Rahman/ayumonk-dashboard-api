from __future__ import annotations
"""Service backing GET /api/v1/dashboard/leaderboard.

Returns the weekly Challenges-tab leaderboard for the requesting employee's
company. Ranking column is `user_xp.xp_this_week` (reset every Monday by
pg_cron); the `+42%`-style delta is computed against last week's XP, which is
NOT stored on user_xp and is summed on-the-fly from
`user_challenge_completions` over the previous Mon-Sun window.

Schema-mapping notes (spec named columns that don't literally exist):
* `company_users.user_id` — there isn't one. user_xp / user_challenge_completions
  carry the auth `users.id` (Integer) directly, and we join company_users to
  users by email (single shared DB across the two services).
* `users.full_name` — the auth `users` row has no name column; the display
  name lives on `company_users.full_name`.
* `company_users.location` — schema gap (also called out in
  EmployeeSnapshotsService). Location is at company granularity here, via
  `companies.location_id` -> `locations.name`.
* `company_users.department` — prefer the FK-resolved `departments.name`,
  fall back to the legacy free-text `company_users.department`.
"""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.schemas.leaderboard import (
    LeaderboardEntry,
    WeeklyLeaderboardResponse,
)


# Roster + this-week XP for the company. LEFT JOIN on user_xp so employees
# with no XP row yet still appear with 0 XP. Tie-break by full_name to keep
# the ordering stable when many employees share the same xp_this_week.
_ROSTER_SQL = """
SELECT
    u.id                                    AS user_id,
    cu.full_name                            AS full_name,
    COALESCE(d.name, cu.department)         AS department,
    l.name                                  AS location,
    COALESCE(ux.xp_this_week, 0)            AS xp_this_week,
    COALESCE(ux.current_level, 1)           AS current_level,
    COALESCE(ux.level_label, 'Seedling')    AS level_label
FROM company_users cu
JOIN users         u ON LOWER(u.email) = LOWER(cu.email)
JOIN companies     c ON c.id = cu.company_id
LEFT JOIN departments d ON d.id = cu.department_id
LEFT JOIN locations   l ON l.id = c.location_id
LEFT JOIN user_xp     ux ON ux.user_id = u.id
WHERE cu.company_id = :company_id
  AND cu.is_active  = TRUE
  AND cu.is_deleted = FALSE
  AND u.is_active   = TRUE
ORDER BY COALESCE(ux.xp_this_week, 0) DESC, cu.full_name ASC
"""


# Sum of xp_earned per user for the previous Mon-Sun window. Scoped to the
# same company so cross-tenant completions can never leak in.
_LAST_WEEK_XP_SQL = """
SELECT
    user_id,
    COALESCE(SUM(xp_earned), 0) AS xp_last_week
FROM user_challenge_completions
WHERE company_id       = :company_id
  AND completion_date >= :last_monday
  AND completion_date <= :last_sunday
  AND is_deleted       = FALSE
GROUP BY user_id
"""


_TOP_N = 10


class LeaderboardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_weekly_leaderboard(
        self,
        *,
        user_id: int,
        company_id: UUID | None,
    ) -> WeeklyLeaderboardResponse:
        if company_id is None:
            raise BusinessException(
                message="No company assignment on current user",
                status_code=403,
            )

        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        last_monday = this_monday - timedelta(days=7)
        last_sunday = this_monday - timedelta(days=1)
        this_sunday = this_monday + timedelta(days=6)

        roster_rows = (await self.db.execute(
            sql_text(_ROSTER_SQL), {"company_id": company_id}
        )).mappings().all()

        if not any(r["user_id"] == user_id for r in roster_rows):
            raise BusinessException(
                message="User does not belong to this company",
                status_code=403,
            )

        last_week_rows = (await self.db.execute(
            sql_text(_LAST_WEEK_XP_SQL),
            {
                "company_id":  company_id,
                "last_monday": last_monday,
                "last_sunday": last_sunday,
            },
        )).mappings().all()
        last_week_xp: dict[int, int] = {
            row["user_id"]: int(row["xp_last_week"] or 0) for row in last_week_rows
        }

        # Standard competition ranking ("1224"): tied XP -> same rank, the next
        # rank skips by the size of the tie. Matches Test 4 in the spec.
        ranked: list[dict[str, Any]] = []
        current_rank = 1
        prev_xp: int | None = None
        for i, row in enumerate(roster_rows):
            xp_this_week = int(row["xp_this_week"] or 0)
            if prev_xp is None or xp_this_week != prev_xp:
                current_rank = i + 1
            xp_lw = last_week_xp.get(row["user_id"], 0)
            ranked.append({
                "rank":          current_rank,
                "user_id":       row["user_id"],
                "full_name":     row["full_name"] or "",
                "department":    row["department"],
                "location":      row["location"],
                "xp_this_week":  xp_this_week,
                "xp_last_week":  xp_lw,
                "current_level": int(row["current_level"] or 1),
                "level_label":   row["level_label"] or "Seedling",
            })
            prev_xp = xp_this_week

        top_n_raw = ranked[:_TOP_N]
        user_in_top_n = any(r["user_id"] == user_id for r in top_n_raw)

        top_n = [
            self._to_entry(r, is_current_user=(user_in_top_n and r["user_id"] == user_id))
            for r in top_n_raw
        ]

        your_position: LeaderboardEntry | None = None
        if not user_in_top_n:
            me = next(r for r in ranked if r["user_id"] == user_id)
            your_position = self._to_entry(me, is_current_user=True)

        return WeeklyLeaderboardResponse(
            week_start=this_monday.isoformat(),
            week_end=this_sunday.isoformat(),
            leaderboard=top_n,
            your_position=your_position,
        )

    # ------------------------------------------------------------------
    # Display formatting helpers
    # ------------------------------------------------------------------

    def _to_entry(self, row: dict[str, Any], *, is_current_user: bool) -> LeaderboardEntry:
        display_change, change_type = self._format_change(
            xp_this_week=row["xp_this_week"],
            xp_last_week=row["xp_last_week"],
        )
        return LeaderboardEntry(
            rank=row["rank"],
            rank_label=self._rank_label(row["rank"]),
            user_id=row["user_id"],
            display_name=self._display_name(row["full_name"]),
            subtext=self._subtext(row["department"], row["location"]),
            xp_this_week=row["xp_this_week"],
            xp_last_week=row["xp_last_week"],
            display_change=display_change,
            change_type=change_type,
            current_level=row["current_level"],
            level_label=row["level_label"],
            is_current_user=is_current_user,
        )

    @staticmethod
    def _display_name(full_name: str) -> str:
        parts = (full_name or "").strip().split()
        if not parts:
            return ""
        if len(parts) >= 2:
            return f"{parts[0]} {parts[-1][0]}."
        return parts[0]

    @staticmethod
    def _subtext(department: str | None, location: str | None) -> str:
        bits = [b for b in (department, location) if b]
        return " · ".join(bits)

    @staticmethod
    def _rank_label(n: int) -> str:
        # Teens (11/12/13) always take "th"; otherwise suffix off the last digit.
        if 11 <= (n % 100) <= 13:
            return f"{n}th"
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    @staticmethod
    def _format_change(*, xp_this_week: int, xp_last_week: int) -> tuple[str, str]:
        if xp_last_week > 0:
            pct = ((xp_this_week - xp_last_week) / xp_last_week) * 100
            rounded = round(pct)
            label = f"+{rounded}%" if rounded >= 0 else f"{rounded}%"
            return label, "percentage"
        if xp_this_week > 0:
            return f"+{xp_this_week} XP", "absolute"
        return "0 XP", "absolute"
