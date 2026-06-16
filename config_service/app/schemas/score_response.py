from __future__ import annotations
from pydantic import BaseModel


class EmployeeScoreSchema(BaseModel):
    employee_email: str
    total_score: int
