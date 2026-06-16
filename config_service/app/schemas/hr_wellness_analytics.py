from __future__ import annotations
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Toggle definitions — GET /hr/wellness-dimensions
# ---------------------------------------------------------------------------


class WellnessDimensionToggle(BaseModel):
    """One entry in the toggle bar above the chart. `WellnessIndex` is
    hardcoded first (order=0); the remaining entries come from
    `wellness_dimension` ordered by `display_order`."""

    key: str
    label: str
    order: int

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Wellness by dimension chart — GET /hr/wellness-by-dimension
# ---------------------------------------------------------------------------


class DimensionChartBucket(BaseModel):
    """One bar in the by-department or by-location grouping."""

    label: str
    value: Decimal


class WellnessByDimensionResponse(BaseModel):
    dimension: str
    by_department: list[DimensionChartBucket]
    by_location: list[DimensionChartBucket]


# ---------------------------------------------------------------------------
# Gender-wise wellness + productivity — GET /hr/gender-wellness
# ---------------------------------------------------------------------------


class GenderWellnessRow(BaseModel):
    """One row in the horizontal-bar chart (Male / Female / Other)."""

    gender: str
    wellness_score: Decimal
    productivity_score: Optional[Decimal] = None


# ---------------------------------------------------------------------------
# Location x Department heatmap — GET /hr/heatmap/location-department
# ---------------------------------------------------------------------------


class HeatmapCell(BaseModel):
    """One cell inside a heatmap row — `value` is null when no employees
    exist at that location x department intersection."""

    department: str
    value: Optional[Decimal] = None


class HeatmapRow(BaseModel):
    """All department cells for a single location, in the order returned
    by `WellnessHeatmapResponse.departments`."""

    location: str
    scores: list[HeatmapCell]


class WellnessHeatmapResponse(BaseModel):
    locations: list[str]
    departments: list[str]
    heatmap: list[HeatmapRow]


# ---------------------------------------------------------------------------
# HR Analytics summary cards — GET /hr/summary-cards
# ---------------------------------------------------------------------------


class HrCardValue(BaseModel):
    """One of the six summary cards rendered at the top of the HR Analytics
    dashboard. `value` is null when the underlying dimension isn't configured
    for the caller's company or when no employees have any data to aggregate."""

    value: Optional[Decimal] = None
    unit: str
    label: str
    subtext: Optional[str] = None


class HrSummaryCardsResponse(BaseModel):
    avg_wellness: HrCardValue
    productivity: HrCardValue
    engagement: HrCardValue
    absenteeism: HrCardValue
    sleep_score: HrCardValue
    stress_score: HrCardValue


# ---------------------------------------------------------------------------
# Employee count — GET /hr/employee-count
# ---------------------------------------------------------------------------


class EmployeeCountResponse(BaseModel):
    """Lightweight badge powering "X of Y employees in scope" on the HR
    Analytics filter strip. ``total`` is the company headcount irrespective
    of filters; ``filtered`` is the count after applying the seven shared
    HR filter axes."""

    total: int
    filtered: int


# ---------------------------------------------------------------------------
# Headcount per bucket — GET /hr/headcount
# ---------------------------------------------------------------------------


class HeadcountBucket(BaseModel):
    """One bar in the by-department / by-location grouping."""

    label: str
    count: int


class HeadcountResponse(BaseModel):
    """Headcount broken down by department and by location. Used to size
    bubbles on the Wellness×Productivity scatter plot (and any other chart
    that needs to weight a series by department headcount)."""

    by_department: list[HeadcountBucket]
    by_location: list[HeadcountBucket]
