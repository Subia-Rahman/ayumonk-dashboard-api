from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PushKeys(BaseModel):
    p256dh: str = Field(..., min_length=1, max_length=255)
    auth: str = Field(..., min_length=1, max_length=255)


class PushSubscriptionPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    endpoint: str = Field(..., min_length=1)
    expirationTime: Optional[int] = None
    keys: PushKeys


class PushUnsubscribePayload(BaseModel):
    endpoint: str = Field(..., min_length=1)


class PushNotificationPayload(BaseModel):
    title: str
    body: Optional[str] = None
    icon: Optional[str] = None
    url: Optional[str] = None
