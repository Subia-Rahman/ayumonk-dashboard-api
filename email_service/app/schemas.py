from __future__ import annotations
from pydantic import BaseModel
from typing import List, Optional

class EmailRequest(BaseModel):
    to: List[str]
    subject: str
    body: str
    html: Optional[bool] = False
