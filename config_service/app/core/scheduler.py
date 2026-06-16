from __future__ import annotations
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.services.reminder_dispatcher import ReminderDispatcher


logger = get_file_logger(name="scheduler", prefix="scheduler")


_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


async def _run_reminder_dispatch():
    dispatcher = ReminderDispatcher(time_window_minutes=1)
    try:
        await dispatcher.dispatch_due_reminders()
    except Exception:
        logger.exception("Reminder dispatch run failed")


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        return

    # coalesce=True   — if multiple firings were missed (e.g. process restart),
    #                   only run once instead of catching up.
    # max_instances=1 — never overlap runs. If one run is still going when the
    #                   next minute ticks, the new firing is skipped (and logged
    #                   by APScheduler as "execution skipped: maximum number of
    #                   running instances reached").
    # misfire_grace_time=30 — drop the firing entirely if we're more than 30s
    #                   late. Avoids dispatching stale reminders after a long
    #                   pause (deploy, GC, etc.).
    scheduler.add_job(
        _run_reminder_dispatch,
        trigger=CronTrigger(minute="*"),
        id="reminder_dispatch",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=30,
    )
    scheduler.start()
    logger.info("APScheduler started with reminder_dispatch job (every minute)")


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down")
    _scheduler = None
