from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel


class EmployeeSnapshotRow(BaseModel):
    """One row per employee. Every numeric field is nullable: missing KPI
    scores / missing mappings / missing demographic fields all surface as
    `null` rather than 0, so the dashboard can distinguish "no data" from
    "zero"."""

    dept: Optional[str] = None
    loc: Optional[str] = None
    age: Optional[str] = None
    gender: Optional[str] = None
    wellnessIndex: Optional[float] = None  # noqa: N815 — wire format is camelCase.
    productivity: Optional[float] = None
    engagement: Optional[float] = None
    absenteeism: Optional[float] = None
    sleep: Optional[float] = None
    stress: Optional[float] = None
    nutrition: Optional[float] = None


class EmployeeSnapshotMeta(BaseModel):
    companyId: UUID  # noqa: N815
    totalEmployees: int  # noqa: N815
    updatedAt: datetime  # noqa: N815
    missingMappings: list[str] = []  # noqa: N815
    missingKpis: list[str] = []  # noqa: N815
    # Path-1 schema gap: company_users has no location_id, so every employee
    # in a single-location company shares one loc value.
    locationGranularity: Literal["company", "employee"] = "company"  # noqa: N815


class EmployeeSnapshotResponse(BaseModel):
    data: list[EmployeeSnapshotRow]
    meta: EmployeeSnapshotMeta
