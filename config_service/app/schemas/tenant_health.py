from __future__ import annotations
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class TenantHealthRow(BaseModel):
    id: UUID
    company_name: Optional[str] = None
    industry: Optional[str] = None
    size_bucket: Optional[str] = None
    no_of_employees: Optional[int] = None
    registered_employees: int = 0
    active_employees: int = 0
    onboarding_pct: float = 0.0
    last_activity: Optional[datetime] = None
    days_since_activity: Optional[int] = None
