import asyncio
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.config import settings
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import AsyncSessionLocal
from config_service.app.models.company_users import CompanyUser
from config_service.app.models.notification import Notification
from config_service.app.models.reminder_settings import ReminderSettings
from config_service.app.repositories.notification import NotificationRepository
from config_service.app.repositories.push_subscription import (
    PushSubscriptionRepository,
)
from config_service.app.repositories.reminder_settings import (
    ReminderSettingsRepository,
)
from config_service.app.services.email_client import EmailClient
from config_service.app.services.push import send_push_notification
from config_service.app.services.reminder_settings import ReminderSettingsService


logger = get_file_logger(name="reminder_dispatcher", prefix="reminder_dispatcher")


REMINDER_SUBJECT = "Daily Reminder"
REMINDER_BODY_TEMPLATE = (
    "Hi {name},\n\n"
    "This is your scheduled reminder ({reminder_types}).\n\n"
    "Open the app to take action.\n\n"
    "— Reminder Service"
)


REMINDER_TYPE_TO_NOTIFICATION = {
    "daily_challenge": {
        "type": "daily_challenge",
        "title": "Daily challenge reminder",
        "icon": "clipboard",
        "action_type": "open_app",
    },
    "streak_alert": {
        "type": "streak_alert",
        "title": "Streak at Risk!",
        "icon": "flame",
        "action_type": "mark_done",
    },
    "program_ending": {
        "type": "program_ending",
        "title": "Program ending soon",
        "icon": "calendar",
        "action_type": "view_schedule",
    },
    "new_program": {
        "type": "new_program",
        "title": "New program starts tomorrow",
        "icon": "sprout",
        "action_type": "preview",
    },
    "badge_milestone": {
        "type": "badge_unlock",
        "title": "Badge milestone alert",
        "icon": "medal",
        "action_type": "view_badge",
    },
}


_TOGGLE_TO_NOTIFICATION_META = [
    ("daily_challenge", REMINDER_TYPE_TO_NOTIFICATION["daily_challenge"]),
    ("streak_alert", REMINDER_TYPE_TO_NOTIFICATION["streak_alert"]),
    ("program_ending", REMINDER_TYPE_TO_NOTIFICATION["program_ending"]),
    ("new_program", REMINDER_TYPE_TO_NOTIFICATION["new_program"]),
    ("badge_milestone", REMINDER_TYPE_TO_NOTIFICATION["badge_milestone"]),
]

_REMINDER_TYPE_LABELS = [
    ("daily_challenge", "Daily challenge"),
    ("streak_alert", "Streak at risk"),
    ("program_ending", "Program ending soon"),
    ("new_program", "New program tomorrow"),
    ("badge_milestone", "Badge milestone"),
]


class ReminderDispatcher:
    """Reminder fan-out.

    Each minute the scheduler invokes ``dispatch_due_reminders``. The flow:

    1. Open a short-lived session, load all enabled reminder rows, close it.
    2. Filter candidates in memory (timezone math, suppression, idempotency).
    3. Fan out the survivors with bounded concurrency. Each task opens its
       own session for its own user — so a slow email or SMTP timeout for
       one user does not hold a DB connection that other API requests need.
    """

    def __init__(
        self,
        email_client: Optional[EmailClient] = None,
        time_window_minutes: int = 1,
        max_concurrency: Optional[int] = None,
    ):
        self.email_client = email_client or EmailClient()
        self.time_window_minutes = time_window_minutes
        self.max_concurrency = max_concurrency or settings.REMINDER_DISPATCH_CONCURRENCY

    # ----------------------------------------------------------------- public

    async def dispatch_due_reminders(
        self,
        *,
        now_utc: Optional[datetime] = None,
    ) -> int:
        now_utc = now_utc or datetime.now(timezone.utc).replace(tzinfo=None)

        # Step 1: fast read of all enabled reminders, then release the
        # connection. This is the only DB touch on the main coroutine.
        async with AsyncSessionLocal() as session:
            repo = ReminderSettingsRepository(session)
            all_entities = await repo.list_active_due()

        # Step 2: pure-Python filter (no I/O).
        candidates: list[tuple[ReminderSettings, list[str], object]] = []
        for entity in all_entities:
            if ReminderSettingsService.is_reminder_suppressed(entity, now_utc):
                continue
            if not self._is_within_time_window(entity, now_utc):
                continue
            user_local_date = self._user_local_date(entity, now_utc)
            if entity.last_dispatched_on == user_local_date:
                continue
            reminder_types = self._collect_active_reminder_types(entity)
            if not reminder_types:
                continue
            candidates.append((entity, reminder_types, user_local_date))

        if not candidates:
            logger.info("No reminders due at %s", now_utc.isoformat())
            return 0

        logger.info(
            "Dispatching %s candidate reminder(s) at %s (concurrency=%s)",
            len(candidates), now_utc.isoformat(), self.max_concurrency,
        )

        # Step 3: fan out with bounded concurrency.
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _bounded(entity_t, types_t, local_date_t):
            async with semaphore:
                return await self._dispatch_one(entity_t, types_t, local_date_t)

        results = await asyncio.gather(
            *[_bounded(*c) for c in candidates],
            return_exceptions=True,
        )

        sent = sum(1 for r in results if r is True)
        failed = len(results) - sent
        logger.info(
            "Reminder dispatch complete | sent=%s | failed=%s | total=%s",
            sent, failed, len(results),
        )
        return sent

    # ---------------------------------------------------------------- per-user

    async def _dispatch_one(
        self,
        entity: ReminderSettings,
        reminder_types: list[str],
        user_local_date,
    ) -> bool:
        """Owns one user's dispatch end-to-end. Opens its own session, so a
        slow SMTP call does not pin a connection from the shared pool any
        longer than necessary. Returns True on success, False on failure
        (errors are logged and never re-raised — one bad user shouldn't kill
        the batch)."""
        try:
            async with AsyncSessionLocal() as session:
                user = await self._load_user(session, entity.user_id)
                if not user or not user.email:
                    logger.warning(
                        "Skipping reminder; user/email missing for user_id=%s",
                        entity.user_id,
                    )
                    return False

                await self._send(entity, user, reminder_types, session)
                await self._record_notifications(session, entity, user)
                await session.execute(
                    update(ReminderSettings)
                    .where(ReminderSettings.id == entity.id)
                    .values(last_dispatched_on=user_local_date)
                )
                await session.commit()
                return True
        except Exception:
            logger.exception(
                "Failed to dispatch reminder for user_id=%s", entity.user_id
            )
            return False

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _user_local_date(entity: ReminderSettings, now_utc: datetime):
        try:
            tz = ZoneInfo(entity.timezone or "UTC")
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        return now_utc.replace(tzinfo=timezone.utc).astimezone(tz).date()

    def _is_within_time_window(
        self, entity: ReminderSettings, now_utc: datetime
    ) -> bool:
        try:
            tz = ZoneInfo(entity.timezone or "UTC")
        except ZoneInfoNotFoundError:
            logger.warning(
                "Invalid timezone '%s' on user_id=%s, falling back to UTC",
                entity.timezone, entity.user_id,
            )
            tz = ZoneInfo("UTC")

        local_now = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)
        target = entity.reminder_time
        local_minutes = local_now.hour * 60 + local_now.minute
        target_minutes = target.hour * 60 + target.minute
        diff = abs(local_minutes - target_minutes)
        return diff <= self.time_window_minutes

    @staticmethod
    def _collect_active_reminder_types(entity: ReminderSettings) -> list[str]:
        return [label for field, label in _REMINDER_TYPE_LABELS if getattr(entity, field)]

    @staticmethod
    async def _load_user(session: AsyncSession, user_id) -> Optional[CompanyUser]:
        stmt = select(CompanyUser).where(
            CompanyUser.id == user_id,
            CompanyUser.is_deleted == False,
            CompanyUser.is_active == True,
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    async def _send(
        self,
        entity: ReminderSettings,
        user: CompanyUser,
        reminder_types: list[str],
        session: AsyncSession,
    ) -> None:
        body = REMINDER_BODY_TEMPLATE.format(
            name=user.full_name or user.email,
            reminder_types=", ".join(reminder_types),
        )

        # Each channel is independent; one failing should not skip the others.
        if entity.email_enabled:
            try:
                await self.email_client.send_email(
                    to=[user.email],
                    subject=REMINDER_SUBJECT,
                    body=body,
                    html=False,
                )
                logger.info("Email reminder sent to %s", user.email)
            except Exception:
                logger.exception("Email reminder failed for user_id=%s", user.id)

        if entity.push_enabled:
            try:
                await self._send_push(session, user, reminder_types)
            except Exception:
                logger.exception("Push reminder failed for user_id=%s", user.id)

        if entity.whatsapp_enabled:
            logger.info(
                "[MOCK WHATSAPP] user_id=%s | types=%s", user.id, reminder_types
            )

    @staticmethod
    async def _send_push(
        session: AsyncSession,
        user: CompanyUser,
        reminder_types: list[str],
    ) -> None:
        push_repo = PushSubscriptionRepository(session)
        subs = await push_repo.list_by_user_id(user.id)
        if not subs:
            logger.info("No push subscriptions for user_id=%s; skipping push", user.id)
            return

        payload = {
            "title": REMINDER_SUBJECT,
            "body": (
                f"You have {len(reminder_types)} reminder"
                f"{'s' if len(reminder_types) != 1 else ''}: "
                + ", ".join(reminder_types)
            ),
            "icon": "/icon-192.png",
            "url": "/",
        }

        # Fan out push deliveries for THIS user in parallel — they're
        # independent network calls. The outer dispatcher already bounds
        # how many users run at once, so this won't explode concurrency.
        async def _deliver(sub):
            subscription_info = {
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            }
            result = await asyncio.to_thread(
                send_push_notification, subscription_info, payload
            )
            if result.success:
                logger.info(
                    "Push reminder sent | user_id=%s | endpoint=%s",
                    user.id, sub.endpoint,
                )
                return None
            if result.expired:
                return sub.endpoint
            return None

        outcomes = await asyncio.gather(
            *[_deliver(s) for s in subs], return_exceptions=True
        )
        expired_endpoints = [e for e in outcomes if isinstance(e, str)]

        for endpoint in expired_endpoints:
            try:
                await push_repo.delete_by_endpoint(endpoint)
                logger.info("Evicted expired push subscription | endpoint=%s", endpoint)
            except Exception:
                logger.exception(
                    "Failed to evict expired push subscription | endpoint=%s",
                    endpoint,
                )

    async def _record_notifications(
        self,
        session: AsyncSession,
        entity: ReminderSettings,
        user: CompanyUser,
    ) -> None:
        """Insert one Notification row per active reminder type.

        We add all rows to the session and let the outer per-user commit
        flush them in a single round-trip instead of committing once per
        row. NotificationRepository.create commits per call — we bypass it
        deliberately here for batching.
        """
        company_id = getattr(user, "company_id", None)

        for field, meta in _TOGGLE_TO_NOTIFICATION_META:
            if not getattr(entity, field):
                continue
            session.add(
                Notification(
                    user_id=user.id,
                    company_id=company_id,
                    type=meta["type"],
                    title=meta["title"],
                    body=f"Reminder triggered for {meta['title'].lower()}.",
                    icon=meta["icon"],
                    action_type=meta["action_type"],
                    action_payload={"source": "reminder_dispatcher"},
                )
            )
        # No commit here — `_dispatch_one` commits once at the end.
