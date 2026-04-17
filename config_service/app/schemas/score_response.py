from pydantic import BaseModel


class EmployeeScoreSchema(BaseModel):
    employee_email: str
    total_score: int
