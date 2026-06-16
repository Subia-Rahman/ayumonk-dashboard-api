from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.schemas.wellness_trends import (
    Period,
    WellnessImprovementTag,
    WellnessTrendPoint,
    WellnessTrendSeries,
    WellnessTrendsResponse,
)
from config_service.app.repositories.sessions import SessionRepository
from config_service.app.services.sessions import SessionService


DEFAULT_BUCKETS = {
    "daily": 7,
    "weekly": 6,
    "monthly": 6,
}


KPI_COLOR_PALETTE = [
    "#a855f7",  # social - violet
    "#22d3ee",  # hydration - cyan
    "#f97316",  # recovery - orange
    "#22c55e",  # nutrition - green
    "#ec4899",  # mood - pink
    "#facc15",  # sleep - yellow
]


class WellnessTrendsService:
    """Aggregates an employee's submissions into chart-ready buckets."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.session_service = SessionService(SessionRepository(db))

    async def get_trends(
        self,
        *,
        email: str,
        period: Period = "weekly",
        bucket_count: Optional[int] = None,
    ) -> WellnessTrendsResponse:
        bucket_count = bucket_count or DEFAULT_BUCKETS[period]
        submissions = await self.session_service.get_user_submitted_sessions(email)

        # Flatten per-response per-KPI rows.
        flat: list[dict] = []
        for session in submissions:
            for response in session.get("responses", []):
                submitted_at = self._coerce_datetime(response.get("submitted_at"))
                if submitted_at is None:
                    continue
                for kpi in response.get("kpi_scores", []) or []:
                    kpi_key = kpi.get("kpi_key")
                    if kpi_key is None:
                        continue
                    avg = kpi.get("average_score")
                    if avg is None:
                        continue
                    flat.append(
                        {
                            "submitted_at": submitted_at,
                            "kpi_key": kpi_key,
                            "kpi_name": kpi.get("kpi_name") or "",
                            "average_score": float(avg),
                        }
                    )

        if not flat:
            return self._empty_response(period, bucket_count)

        bucket_keys = self._build_bucket_keys(flat, period, bucket_count)
        # bucket_keys is ordered oldest -> newest

        # Group: kpi_key -> bucket_key -> [scores]
        kpi_bucket: dict[str, dict] = defaultdict(lambda: defaultdict(list))
        kpi_names: dict[str, str] = {}
        # Overall: bucket_key -> [scores]
        overall_bucket: dict = defaultdict(list)

        bucket_set = set(bucket_keys)
        for row in flat:
            bk = self._bucket_key(row["submitted_at"], period)
            if bk not in bucket_set:
                continue
            kpi_key = str(row["kpi_key"])
            kpi_bucket[kpi_key][bk].append(row["average_score"])
            kpi_names[kpi_key] = row["kpi_name"] or kpi_names.get(kpi_key, "")
            overall_bucket[bk].append(row["average_score"])

        # Build per-KPI series
        series: list[WellnessTrendSeries] = []
        improvements: list[WellnessImprovementTag] = []
        for idx, (kpi_key, buckets) in enumerate(kpi_bucket.items()):
            points = self._materialize_points(buckets, bucket_keys, period)
            delta = self._compute_delta_percent(points)
            series.append(
                WellnessTrendSeries(
                    kpi_key=UUID(kpi_key),
                    kpi_name=kpi_names.get(kpi_key, "") or "Unnamed KPI",
                    color=KPI_COLOR_PALETTE[idx % len(KPI_COLOR_PALETTE)],
                    points=points,
                    delta_percent=delta,
                )
            )
            if delta is not None and delta > 0:
                improvements.append(
                    WellnessImprovementTag(
                        kpi_key=UUID(kpi_key),
                        kpi_name=kpi_names.get(kpi_key, "") or "Unnamed KPI",
                        delta_percent=round(delta, 1),
                    )
                )

        # Overall series
        overall_points = self._materialize_points(overall_bucket, bucket_keys, period)
        overall = WellnessTrendSeries(
            kpi_key=None,
            kpi_name="Overall",
            color="#fb923c",  # orange line in the screenshot
            points=overall_points,
            delta_percent=self._compute_delta_percent(overall_points),
        )

        # Sort series by KPI name for stable output; sort improvements desc by delta
        series.sort(key=lambda s: s.kpi_name.lower())
        improvements.sort(key=lambda i: i.delta_percent, reverse=True)
        top_improvements = improvements[:2]

        return WellnessTrendsResponse(
            period=period,
            bucket_count=len(bucket_keys),
            overall=overall,
            series=series,
            top_improvements=top_improvements,
            insight=self._build_insight(top_improvements, overall.delta_percent),
        )

    def _materialize_points(
        self,
        buckets: dict,
        bucket_keys: list,
        period: Period,
    ) -> list[WellnessTrendPoint]:
        points: list[WellnessTrendPoint] = []
        for idx, bk in enumerate(bucket_keys, start=1):
            scores = buckets.get(bk) or []
            avg = round(mean(scores), 2) if scores else 0.0
            points.append(
                WellnessTrendPoint(
                    bucket_label=f"S{idx}",
                    bucket_index=idx,
                    bucket_at=self._bucket_anchor(bk, period),
                    average_score=avg,
                )
            )
        return points

    def _build_bucket_keys(
        self,
        flat: list[dict],
        period: Period,
        bucket_count: int,
    ) -> list:
        latest = max(row["submitted_at"] for row in flat)
        keys: list = []
        cursor = self._bucket_key(latest, period)
        keys.append(cursor)
        for _ in range(bucket_count - 1):
            cursor = self._previous_bucket(cursor, period)
            keys.append(cursor)
        keys.reverse()
        return keys

    @staticmethod
    def _bucket_key(dt: datetime, period: Period):
        if period == "daily":
            return ("d", dt.date())
        if period == "weekly":
            iso = dt.isocalendar()
            return ("w", iso.year, iso.week)
        return ("m", dt.year, dt.month)

    @staticmethod
    def _previous_bucket(key, period: Period):
        if period == "daily":
            return ("d", key[1] - timedelta(days=1))
        if period == "weekly":
            year, week = key[1], key[2]
            anchor = date.fromisocalendar(year, week, 1) - timedelta(days=7)
            iso = anchor.isocalendar()
            return ("w", iso.year, iso.week)
        year, month = key[1], key[2]
        if month == 1:
            return ("m", year - 1, 12)
        return ("m", year, month - 1)

    @staticmethod
    def _bucket_anchor(key, period: Period) -> datetime:
        if period == "daily":
            return datetime.combine(key[1], datetime.min.time())
        if period == "weekly":
            anchor = date.fromisocalendar(key[1], key[2], 1)
            return datetime.combine(anchor, datetime.min.time())
        return datetime(key[1], key[2], 1)

    @staticmethod
    def _coerce_datetime(value) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _compute_delta_percent(points: list[WellnessTrendPoint]) -> Optional[float]:
        non_zero = [p for p in points if p.average_score > 0]
        if len(non_zero) < 2:
            return None
        first = non_zero[0].average_score
        last = non_zero[-1].average_score
        if first == 0:
            return None
        return round(((last - first) / first) * 100, 2)

    @staticmethod
    def _build_insight(
        top: list[WellnessImprovementTag],
        overall_delta: Optional[float],
    ) -> str:
        if not top:
            if overall_delta is None:
                return "Not enough submissions yet to detect a trend."
            if overall_delta < 0:
                return "Scores have dipped recently — consider revisiting your weakest KPI."
            return "Steady scores across the board — keep going."
        if len(top) == 1:
            return f"Most stable gains are showing up in {top[0].kpi_name.lower()}."
        names = [t.kpi_name.lower() for t in top]
        return f"Most stable gains are showing up in {names[0]} and {names[1]}."

    @staticmethod
    def _empty_response(period: Period, bucket_count: int) -> WellnessTrendsResponse:
        empty_points = [
            WellnessTrendPoint(
                bucket_label=f"S{i + 1}",
                bucket_index=i + 1,
                bucket_at=datetime.utcnow(),
                average_score=0.0,
            )
            for i in range(bucket_count)
        ]
        return WellnessTrendsResponse(
            period=period,
            bucket_count=bucket_count,
            overall=WellnessTrendSeries(
                kpi_key=None,
                kpi_name="Overall",
                color="#fb923c",
                points=empty_points,
                delta_percent=None,
            ),
            series=[],
            top_improvements=[],
            insight="No submissions yet — your trend chart will appear here after your first session.",
        )
