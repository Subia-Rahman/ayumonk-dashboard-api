from __future__ import annotations
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
from config_service.app.models.reminder_log import ReminderLog
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
from config_service.app.services.reminder_eligibility import (
    company_has_new_program_opening_soon,
    company_has_program_ending_soon,
    resolve_auth_user_id_by_email,
    user_has_incomplete_challenges_today,
    user_streak_at_risk,
)
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

        logger.info(
            "REMINDER_DISPATCH_START | now_utc=%s | enabled_rows=%s | "
            "window_minutes=%s",
            now_utc.isoformat(), len(all_entities), self.time_window_minutes,
        )

        # Step 2: pure-Python filter (no I/O). Logs one REMINDER_CANDIDATE
        # line per entity with the full decision context — flip this from
        # INFO to DEBUG once the "all users at the same time" bug is
        # diagnosed. The line includes every value the filter checked so
        # grep-by-user_id reconstructs why a reminder fired (or didn't)
        # at any given tick.
        candidates: list[tuple[ReminderSettings, list[str], object]] = []
        for entity in all_entities:
            suppressed = ReminderSettingsService.is_reminder_suppressed(
                entity, now_utc
            )
            within_window = self._is_within_time_window(entity, now_utc)
            user_local_date = self._user_local_date(entity, now_utc)
            local_now = self._user_local_now(entity, now_utc)
            already_dispatched = entity.last_dispatched_on == user_local_date
            reminder_types = self._collect_active_reminder_types(entity)
            will_dispatch = (
                not suppressed
                and within_window
                and not already_dispatched
                and bool(reminder_types)
            )

            logger.info(
                "REMINDER_CANDIDATE | user_id=%s | reminder_time=%s | tz=%s | "
                "local_now=%s | within_window=%s | suppressed=%s | "
                "last_dispatched_on=%s | local_today=%s | types=%s | "
                "will_dispatch=%s",
                entity.user_id, entity.reminder_time, entity.timezone,
                local_now.strftime("%Y-%m-%d %H:%M"), within_window, suppressed,
                entity.last_dispatched_on, user_local_date, reminder_types,
                will_dispatch,
            )

            if will_dispatch:
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
        the batch).

        Phase 6: before sending, narrows ``reminder_types`` to those that
        pass per-type eligibility (e.g. drop ``program_ending`` when the
        user's company has no programs ending soon). Then writes a
        ``reminder_log`` row per type that actually fired so the
        ReminderSettings "Recent sends" panel has a live data source.
        """
        try:
            async with AsyncSessionLocal() as session:
                user = await self._load_user(session, entity.user_id)
                if not user or not user.email:
                    logger.warning(
                        "Skipping reminder; user/email missing for user_id=%s",
                        entity.user_id,
                    )
                    return False

                # Eligibility filter — narrow the enabled-toggle list to
                # types whose conditions are actually met right now. The
                # mapping from internal field name to the human label
                # used by _send / _collect_active_reminder_types is in
                # _REMINDER_TYPE_LABELS so we can correlate both.
                eligible_fields = await self._eligible_reminder_fields(
                    session=session, entity=entity, user=user
                )
                if not eligible_fields:
                    # Nothing to fire — still mark idempotency so we
                    # don't re-check every minute today. Same row state
                    # the old behaviour would land on after a no-op send.
                    await session.execute(
                        update(ReminderSettings)
                        .where(ReminderSettings.id == entity.id)
                        .values(last_dispatched_on=user_local_date)
                    )
                    await session.commit()
                    return True

                eligible_labels = [
                    label
                    for field, label in _REMINDER_TYPE_LABELS
                    if field in eligible_fields
                ]

                send_result = await self._send(
                    entity, user, eligible_labels, session
                )
                await self._record_notifications(
                    session, entity, user, eligible_fields=eligible_fields
                )
                self._record_reminder_log(
                    session=session,
                    user=user,
                    eligible_fields=eligible_fields,
                    send_result=send_result,
                )
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

    async def _eligible_reminder_fields(
        self,
        *,
        session: AsyncSession,
        entity: ReminderSettings,
        user: CompanyUser,
    ) -> set[str]:
        """Return the subset of enabled toggle field-names that should
        actually fire right now.

        Phase 6 scope: company-level checks (``program_ending`` /
        ``new_program``) against ``kpi_challenges``.

        Phase 6.5 scope: user-level checks (``daily_challenge`` /
        ``streak_alert``) bridged via email →
        ``authentication_service.users.id`` →
        ``user_challenge_completion`` / ``user_streak``. When the email
        can't be resolved to an auth row we conservatively leave the
        user-level toggles in (skip the narrowing) so unlinked users
        don't silently lose their reminders.

        ``badge_milestone`` is event-driven elsewhere — left
        unconditional when the toggle is on.
        """
        enabled = {
            field for field, _ in _REMINDER_TYPE_LABELS if getattr(entity, field)
        }
        if not enabled:
            return set()

        company_id = getattr(user, "company_id", None)

        # ---- Company-level checks (Phase 6) ---------------------------
        if "program_ending" in enabled:
            if not await company_has_program_ending_soon(
                session, company_id=company_id
            ):
                enabled.discard("program_ending")
        if "new_program" in enabled:
            if not await company_has_new_program_opening_soon(
                session, company_id=company_id
            ):
                enabled.discard("new_program")

        # ---- User-level checks (Phase 6.5) ----------------------------
        # Only resolve auth_user_id when at least one user-level toggle
        # is in the enabled set — avoids an unnecessary query for users
        # who only have window/badge toggles on.
        needs_auth_user = bool(
            {"daily_challenge", "streak_alert"} & enabled
        )
        if needs_auth_user:
            auth_user_id = await resolve_auth_user_id_by_email(
                session, email=user.email
            )
            if auth_user_id is None:
                # Unlinked user — skip the narrowing. The conservative
                # path preserves Phase-6 behaviour for unmapped users
                # rather than silently dropping their reminders.
                logger.info(
                    "User-level eligibility skipped (no auth row for email) | "
                    "user_id=%s | email=%s",
                    user.id, user.email,
                )
            else:
                if "daily_challenge" in enabled:
                    if not await user_has_incomplete_challenges_today(
                        session,
                        auth_user_id=auth_user_id,
                        company_id=company_id,
                    ):
                        enabled.discard("daily_challenge")
                if "streak_alert" in enabled:
                    if not await user_streak_at_risk(
                        session, auth_user_id=auth_user_id
                    ):
                        enabled.discard("streak_alert")

        return enabled

    @staticmethod
    def _record_reminder_log(
        *,
        session: AsyncSession,
        user: CompanyUser,
        eligible_fields: set[str],
        send_result: dict,
    ) -> None:
        """Insert one ``reminder_log`` row per (type, channel) attempted.

        ``send_result`` is the bookkeeping dict ``_send`` returns: keys
        ``email`` / ``push`` / ``whatsapp`` each map to ``"sent"`` /
        ``"failed"`` / ``"skipped"``. Channels that ``_send`` didn't
        attempt (toggle off) are omitted from the log — they're not
        attempts."""
        company_id = getattr(user, "company_id", None)
        sent_at = datetime.utcnow()
        for field in eligible_fields:
            for channel, status in send_result.items():
                if status == "skipped":
                    # Channel toggle was off — not an attempt, don't log.
                    continue
                session.add(
                    ReminderLog(
                        user_id=user.id,
                        company_id=company_id,
                        reminder_type=field,
                        channel=channel,
                        status=status,
                        sent_at=sent_at,
                    )
                )

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _user_local_date(entity: ReminderSettings, now_utc: datetime):
        try:
            tz = ZoneInfo(entity.timezone or "UTC")
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        return now_utc.replace(tzinfo=timezone.utc).astimezone(tz).date()

    @staticmethod
    def _user_local_now(entity: ReminderSettings, now_utc: datetime) -> datetime:
        """Symmetric counterpart to _user_local_date — returns the full
        datetime in the user's tz. Only used by the REMINDER_CANDIDATE
        diagnostic log so the operator can see what wall-clock time the
        dispatcher *thought* the user was on when it evaluated the
        time-window check."""
        try:
            tz = ZoneInfo(entity.timezone or "UTC")
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        return now_utc.replace(tzinfo=timezone.utc).astimezone(tz)

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
    ) -> dict:
        """Send via each enabled channel and return a per-channel status
        dict for ``_record_reminder_log``.

        Returns one of ``sent`` / ``failed`` / ``skipped`` per channel:
          * ``sent``    — channel toggle on AND delivery raised no error.
          * ``failed``  — channel toggle on AND delivery raised.
          * ``skipped`` — channel toggle off (NOT logged in reminder_log).
        """
        result: dict = {"email": "skipped", "push": "skipped", "whatsapp": "skipped"}

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
                result["email"] = "sent"
            except Exception:
                logger.exception("Email reminder failed for user_id=%s", user.id)
                result["email"] = "failed"

        if entity.push_enabled:
            try:
                await self._send_push(session, user, reminder_types)
                result["push"] = "sent"
            except Exception:
                logger.exception("Push reminder failed for user_id=%s", user.id)
                result["push"] = "failed"

        if entity.whatsapp_enabled:
            logger.info(
                "[MOCK WHATSAPP] user_id=%s | types=%s", user.id, reminder_types
            )
            # The current WhatsApp leg is a logged mock with no failure
            # mode — count as sent so the log reflects "we attempted".
            result["whatsapp"] = "sent"

        return result

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
        eligible_fields: Optional[set[str]] = None,
    ) -> None:
        """Insert one Notification row per active reminder type.

        We add all rows to the session and let the outer per-user commit
        flush them in a single round-trip instead of committing once per
        row. NotificationRepository.create commits per call — we bypass it
        deliberately here for batching.

        Phase 6: when ``eligible_fields`` is passed, only types in that
        set produce a Notification row — bell icon no longer shows
        "program ending" when nothing's actually ending. Callers that
        skip the param fall back to the pre-Phase-6 behaviour ("all
        enabled toggles produce a row") so legacy callers (none today,
        but defensive) keep working.
        """
        company_id = getattr(user, "company_id", None)

        for field, meta in _TOGGLE_TO_NOTIFICATION_META:
            if not getattr(entity, field):
                continue
            if eligible_fields is not None and field not in eligible_fields:
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
