from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.notification import Notification
from config_service.app.repositories.notification import NotificationRepository
from config_service.app.schemas.notification import (
    BulkActionResponse,
    NotificationActionRequest,
    NotificationCreateRequest,
    NotificationListResponse,
    NotificationResponse,
    NotificationSnoozeRequest,
    UnreadCountResponse,
)


SNOOZE_DURATIONS = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "24h": timedelta(hours=24),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class NotificationService:
    def __init__(self, repo: NotificationRepository):
        self.repo = repo

    async def create(self, payload: NotificationCreateRequest) -> NotificationResponse:
        entity = Notification(
            user_id=payload.user_id,
            company_id=payload.company_id,
            type=payload.type,
            title=payload.title,
            body=payload.body,
            icon=payload.icon,
            action_type=payload.action_type,
            action_payload=payload.action_payload,
        )
        entity = await self.repo.create(entity)
        return NotificationResponse.model_validate(entity)

    async def list(
        self,
        *,
        user_id: UUID,
        skip: int,
        limit: int,
        is_read: Optional[bool],
        type_: Optional[str],
        include_dismissed: bool,
    ) -> NotificationListResponse:
        items, total = await self.repo.list_for_user(
            user_id=user_id,
            skip=skip,
            limit=limit,
            is_read=is_read,
            type_=type_,
            include_dismissed=include_dismissed,
        )
        unread = await self.repo.unread_count(user_id)
        return NotificationListResponse(
            items=[NotificationResponse.model_validate(i) for i in items],
            total=total,
            unread=unread,
            skip=skip,
            limit=limit,
        )

    async def unread_count(self, user_id: UUID) -> UnreadCountResponse:
        return UnreadCountResponse(unread=await self.repo.unread_count(user_id))

    async def mark_read(
        self, notification_id: UUID, user_id: UUID
    ) -> NotificationResponse:
        entity = await self.repo.get_by_id(notification_id, user_id)
        if not entity:
            raise BusinessException(message="Notification not found", status_code=404)
        if not entity.is_read:
            entity.is_read = True
            entity.read_at = _utcnow()
            entity = await self.repo.update(entity)
        return NotificationResponse.model_validate(entity)

    async def dismiss(
        self, notification_id: UUID, user_id: UUID
    ) -> NotificationResponse:
        entity = await self.repo.get_by_id(notification_id, user_id)
        if not entity:
            raise BusinessException(message="Notification not found", status_code=404)
        now = _utcnow()
        entity.dismissed_at = now
        if not entity.is_read:
            entity.is_read = True
            entity.read_at = now
        entity = await self.repo.update(entity)
        return NotificationResponse.model_validate(entity)

    async def snooze(
        self,
        notification_id: UUID,
        user_id: UUID,
        payload: NotificationSnoozeRequest,
    ) -> NotificationResponse:
        delta = SNOOZE_DURATIONS.get(payload.duration)
        if delta is None:
            raise BusinessException(message="Invalid snooze duration", status_code=400)

        entity = await self.repo.get_by_id(notification_id, user_id)
        if not entity:
            raise BusinessException(message="Notification not found", status_code=404)

        entity.snooze_until = _utcnow() + delta
        entity = await self.repo.update(entity)
        return NotificationResponse.model_validate(entity)

    async def record_action(
        self,
        notification_id: UUID,
        user_id: UUID,
        payload: NotificationActionRequest,
    ) -> NotificationResponse:
        """Record that the user took an action on this notification (e.g.
        Mark Done / Commit Now). Marks read and stores the action result in
        action_payload alongside any pre-existing payload.
        """
        entity = await self.repo.get_by_id(notification_id, user_id)
        if not entity:
            raise BusinessException(message="Notification not found", status_code=404)

        now = _utcnow()
        if not entity.is_read:
            entity.is_read = True
            entity.read_at = now

        existing_payload = dict(entity.action_payload or {})
        history = list(existing_payload.get("history", []))
        history.append(
            {
                "action": payload.action,
                "payload": payload.payload,
                "at": now.isoformat(),
            }
        )
        existing_payload["history"] = history
        existing_payload["last_action"] = payload.action
        entity.action_payload = existing_payload

        entity = await self.repo.update(entity)
        return NotificationResponse.model_validate(entity)

    async def mark_all_read(self, user_id: UUID) -> BulkActionResponse:
        affected = await self.repo.mark_all_read(user_id, _utcnow())
        return BulkActionResponse(affected=affected)

    async def clear_all(self, user_id: UUID) -> BulkActionResponse:
        affected = await self.repo.clear_all(user_id, _utcnow())
        return BulkActionResponse(affected=affected)
