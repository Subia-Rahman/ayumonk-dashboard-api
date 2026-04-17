from uuid import UUID
from pydantic import BaseModel


class KPIOptionResponse(BaseModel):
    option_number: int | None = None
    option_text: str | None = None
    score: int | None = None


class KPIQuestionResponse(BaseModel):
    id: UUID
    question_code: str
    question_text: str
    reverse_code: bool
    options: list[KPIOptionResponse]


class KPIResponse(BaseModel):
    kpi_key: UUID
    display_name: str
    questions: list[KPIQuestionResponse]


class ThemeHierarchyResponse(BaseModel):
    theme_key: UUID
    theme_display_name: str
    kpis: list[KPIResponse]
