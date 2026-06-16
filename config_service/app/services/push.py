from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any

from pywebpush import WebPushException, webpush

from config_service.app.core.config import settings
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.models.push_subscription import PushSubscription
from config_service.app.repositories.push_subscription import (
    PushSubscriptionRepository,
)
from config_service.app.schemas.push import PushSubscriptionPayload


@dataclass(frozen=True)
class PushDeliveryResult:
    success: bool
    expired: bool  # Subscription is permanently gone — caller should delete it.


logger = get_file_logger(name="push_service", prefix="push_service")


class PushSubscriptionService:
    def __init__(self, repo: PushSubscriptionRepository):
        self.repo = repo

    async def subscribe(
        self,
        payload: PushSubscriptionPayload,
        user_id=None,
    ) -> PushSubscription:
        return await self.repo.upsert(
            endpoint=payload.endpoint,
            p256dh=payload.keys.p256dh,
            auth=payload.keys.auth,
            user_id=user_id,
        )

    async def unsubscribe(self, endpoint: str) -> bool:
        return await self.repo.delete_by_endpoint(endpoint)


def send_push_notification(
    subscription: dict[str, Any],
    payload: dict[str, Any],
) -> PushDeliveryResult:
    """Deliver a Web Push message to a single browser subscription.

    `subscription` must contain `endpoint` and `keys.{p256dh, auth}` — i.e.
    the JSON shape produced by `PushSubscription.toJSON()` in the browser.
    `payload` is a dict like `{title, body, icon, url}` that is JSON-encoded
    and handed to the service worker.

    Returns a PushDeliveryResult so callers iterating over many subscribers
    can both keep going on transient errors AND evict permanently-dead
    subscriptions (HTTP 404 / 410 from the push service).
    """
    private_key = settings.VAPID_PRIVATE_KEY
    vapid_email = settings.VAPID_EMAIL
    if not private_key or not vapid_email:
        logger.error(
            "send_push_notification | VAPID_PRIVATE_KEY/VAPID_EMAIL not configured"
        )
        return PushDeliveryResult(success=False, expired=False)

    vapid_claims = {"sub": f"mailto:{vapid_email}"}

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=private_key,
            vapid_claims=vapid_claims,
        )
        return PushDeliveryResult(success=True, expired=False)
    except WebPushException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        endpoint = subscription.get("endpoint") if isinstance(subscription, dict) else None
        logger.warning(
            "send_push_notification | WebPushException | status=%s | endpoint=%s | %s",
            status_code,
            endpoint,
            exc,
        )
        return PushDeliveryResult(
            success=False,
            expired=status_code in (404, 410),
        )
