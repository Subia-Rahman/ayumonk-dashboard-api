from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LocationResponse(BaseModel):
    id: UUID
    name: str
    name_normalized: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LocationListResponse(BaseModel):
    items: list[LocationResponse]
    total: int
    skip: int
    limit: int
