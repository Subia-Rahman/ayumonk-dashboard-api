from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator, EmailStr


class SessionCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    company_id: UUID


class SessionUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    company_id: Optional[UUID] = None


class SessionQuestionAddRequest(BaseModel):
    question_ids: List[UUID] = Field(..., min_items=1)


class SessionQuestionRemoveRequest(BaseModel):
    question_ids: List[UUID] = Field(..., min_items=1)


class SessionQuestionSetRequest(BaseModel):
    question_ids: List[UUID] = Field(..., min_items=1)


class SessionQuestionOrderItem(BaseModel):
    question_id: UUID
    display_order: int = Field(..., ge=1)


class SessionQuestionOrderUpdateRequest(BaseModel):
    items: List[SessionQuestionOrderItem] = Field(..., min_items=1)

    @validator("items")
    def ensure_unique_order_and_questions(cls, value):
        question_ids = {item.question_id for item in value}
        display_orders = {item.display_order for item in value}

        if len(question_ids) != len(value):
            raise ValueError("question_id values must be unique")
        if len(display_orders) != len(value):
            raise ValueError("display_order values must be unique")
        return value


class SessionStatusUpdateRequest(BaseModel):
    is_active: bool


class SessionGenerateFormRequest(BaseModel):
    force_regenerate: bool = False


class SessionQuestionResponse(BaseModel):
    question_id: UUID
    question_code: str
    question_text: str
    reverse_code: bool
    display_order: int


class SessionKPIResponse(BaseModel):
    kpi_key: UUID
    display_name: str
    questions: List[SessionQuestionResponse]


class SessionThemeResponse(BaseModel):
    theme_key: UUID
    theme_display_name: str
    kpis: List[SessionKPIResponse]


class SessionDetailsResponse(BaseModel):
    id: UUID
    company_id: Optional[UUID]
    title: str
    description: Optional[str]
    is_active: bool
    is_published: bool
    published_at: Optional[datetime]
    google_form_id: Optional[str]
    google_form_responder_url: Optional[str]
    created_at: datetime
    updated_at: datetime
    themes: List[SessionThemeResponse]


class SessionSummaryResponse(BaseModel):
    id: UUID
    company_id: Optional[UUID]
    title: str
    description: Optional[str]
    is_active: bool
    is_published: bool
    published_at: Optional[datetime]
    google_form_id: Optional[str]
    google_form_responder_url: Optional[str]
    created_at: datetime
    updated_at: datetime


class SessionGoogleFormResponse(BaseModel):
    session_id: UUID
    form_id: str
    responder_url: str
    script_id: Optional[str]


class SessionFormQuestionResponse(BaseModel):
    question_id: UUID
    question_code: str
    question_text: str
    reverse_code: bool
    display_order: int
    theme_key: UUID
    theme_display_name: str
    kpi_key: UUID
    kpi_display_name: str
    options: list[str]


class SessionFormConfigResponse(BaseModel):
    session_id: UUID
    company_id: Optional[UUID]
    title: str
    description: Optional[str]
    is_published: bool
    published_at: Optional[datetime]
    preview_url: str
    final_url: Optional[str]
    questions: list[SessionFormQuestionResponse]


class SessionFormAnswerRequest(BaseModel):
    question_id: UUID
    selected_option: str = Field(..., min_length=1)


class SessionFormSubmissionRequest(BaseModel):
    email: EmailStr
    answers: list[SessionFormAnswerRequest] = Field(..., min_items=1)


class SessionFormSubmissionResponse(BaseModel):
    response_id: str


class SessionSuggestionTrigger(BaseModel):
    trigger_mode: str
    risk_level: Optional[str] = None
    kpi_key: Optional[UUID] = None
    kpi_display_name: Optional[str] = None
    kpi_average_score: Optional[float] = None
    question_key: Optional[UUID] = None
    question_text: Optional[str] = None
    question_score: Optional[float] = None
    score_threshold_below: Optional[int] = None
    score_threshold_above: Optional[int] = None
    priority: int


class SessionSuggestionItem(BaseModel):
    suggestion_id: UUID
    suggestion_type: str
    title: str
    description: Optional[str]
    url: Optional[str]
    dosha_type: str
    difficulty: Optional[str]
    duration_mins: Optional[int]
    triggers: list[SessionSuggestionTrigger]


class SessionSuggestionListResponse(BaseModel):
    session_id: UUID
    response_id: str
    submitted_at: Optional[datetime]
    items: list[SessionSuggestionItem]


class SessionPublishedLinkResponse(BaseModel):
    session_id: UUID
    title: str
    description: Optional[str]
    published_at: Optional[datetime]
    form_url: str


class SessionPublishedLinkListResponse(BaseModel):
    items: list[SessionPublishedLinkResponse]
    total: int
    skip: int
    limit: int
