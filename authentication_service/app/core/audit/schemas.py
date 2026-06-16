from __future__ import annotations
from datetime import datetime, timezone
from config_service.app.core.config import APP_TZ
from pydantic import  BaseModel, field_serializer

class AuditRead(BaseModel):
    created_at: datetime
    updated_at: datetime | None = None
    is_active: bool
    is_deleted: bool

    @field_serializer("created_at", "updated_at")
    def serialize_dt(self, value: datetime | None):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(APP_TZ)

    model_config = {"from_attributes": True}