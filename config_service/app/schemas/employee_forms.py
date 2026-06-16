from __future__ import annotations
from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field


class GoogleFormWebhookRequest(BaseModel):
    company_id: str = Field(..., min_length=1)
    form_id: str = Field(..., min_length=1)
    response_id: str = Field(..., min_length=1)
    respondent_email: str = Field(..., min_length=3)
    submitted_at: Optional[datetime] = None
    answers: Dict[str, str] = Field(default_factory=dict)
