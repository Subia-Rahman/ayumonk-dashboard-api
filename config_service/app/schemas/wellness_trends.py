from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel


Period = Literal["daily", "weekly", "monthly"]


class WellnessTrendPoint(BaseModel):
    bucket_label: str          # "S1" / "S2" / "Mon" / "Wk 12" / "Jan"
    bucket_index: int          # 1-based index used by the chart x-axis
    bucket_at: datetime        # representative timestamp of the bucket
    average_score: float       # 0..5 scale (matches the chart y-axis)


class WellnessTrendSeries(BaseModel):
    kpi_key: Optional[UUID] = None  # null for the overall series
    kpi_name: str                   # "Overall" / "Hydration" / ...
    color: Optional[str] = None     # optional hex color hint for the UI
    points: list[WellnessTrendPoint]
    delta_percent: Optional[float] = None  # change from first to last bucket


class WellnessImprovementTag(BaseModel):
    kpi_key: UUID
    kpi_name: str
    delta_percent: float            # e.g. 17.0 -> "+17%"


class WellnessTrendsResponse(BaseModel):
    period: Period
    bucket_count: int
    overall: WellnessTrendSeries
    series: list[WellnessTrendSeries]
    top_improvements: list[WellnessImprovementTag]
    insight: str
