"""Notifications seed script.

Inserts a representative set of notification rows for one user so the
in-app notifications dropdown can be tested end-to-end. The data mirrors
the UI mockup (Streak at Risk, Badge Unlocks, 2 Challenges Left, Hydration
Program Ending, New Program Starting Tomorrow).

Usage:

    # by email (preferred — looks up the company_users row)
    python -m config_service.app.scripts.seed_notifications --email user@acme.com

    # by user_id (UUID of company_users.id)
    python -m config_service.app.scripts.seed_notifications \\
        --user-id 6f1a4f2e-8a37-4f7d-bf4d-bcb0c4d5e9c1

    # also wipe existing rows for this user before inserting
    python -m config_service.app.scripts.seed_notifications --email user@acme.com --reset
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update

from config_service.app.core.db import AsyncSessionLocal
from config_service.app.models.company_users import CompanyUser
from config_service.app.models.notification import Notification


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _build_seed_rows(user: CompanyUser) -> list[dict]:
    """Return the seed payload, with created_at offsets so timestamps look
    realistic in the UI ("Today 9:00 PM", "Yesterday 8:00 PM", "3 days ago")."""
    now = _utcnow()
    today_9pm = now.replace(hour=21, minute=0, second=0, microsecond=0)
    today_8am = now.replace(hour=8, minute=0, second=0, microsecond=0)
    yesterday_8pm = (now - timedelta(days=1)).replace(
        hour=20, minute=0, second=0, microsecond=0
    )
    three_days_ago = now - timedelta(days=3)
    four_days_ago = now - timedelta(days=4)
    a_week_ago = now - timedelta(days=7)

    return [
        {
            "type": "streak_alert",
            "title": "Streak at Risk!",
            "body": "Your 7-day Hydration streak ends tonight. Complete the challenge before midnight to keep it alive.",
            "icon": "flame",
            "action_type": "mark_done",
            "action_payload": {
                "challenge_id": "hydration-7d",
                "deep_link": "/challenges/hydration-7d",
            },
            "is_read": False,
            "created_at": today_9pm,
        },
        {
            "type": "badge_unlock",
            "title": "Badge Unlocks Tomorrow!",
            "body": "Complete Sleep Before 10PM today and unlock the Sleep Master badge.",
            "icon": "medal",
            "action_type": "commit_now",
            "action_payload": {
                "badge_id": "sleep-master",
                "deep_link": "/badges/sleep-master",
            },
            "is_read": False,
            "created_at": today_8am,
        },
        {
            "type": "challenge_pending",
            "title": "2 Challenges Left Today",
            "body": "Eat Well Today and Daily Mood Check still pending. Takes under 5 minutes to wrap up.",
            "icon": "clipboard",
            "action_type": "open_app",
            "action_payload": {"deep_link": "/app"},
            "is_read": True,
            "read_at": yesterday_8pm + timedelta(minutes=15),
            "created_at": yesterday_8pm,
        },
        {
            "type": "program_ending",
            "title": "Hydration Program Ends in 3 Days",
            "body": "The Hydration KPI window closes 31 Dec. Complete your remaining sessions to qualify for the cohort report.",
            "icon": "calendar",
            "action_type": "view_schedule",
            "action_payload": {
                "program_id": "hydration",
                "deep_link": "/programs/hydration/schedule",
            },
            "is_read": True,
            "read_at": three_days_ago + timedelta(hours=2),
            "created_at": three_days_ago,
        },
        {
            "type": "new_program",
            "title": "New Program Starts Tomorrow",
            "body": "Stress & Recovery program launches tomorrow. Sleep + Stress check-ins begin at 7 AM.",
            "icon": "sprout",
            "action_type": "preview",
            "action_payload": {
                "program_id": "stress-recovery",
                "deep_link": "/programs/stress-recovery/preview",
            },
            "is_read": True,
            "read_at": four_days_ago + timedelta(hours=1),
            "created_at": four_days_ago,
        },
        {
            "type": "daily_challenge",
            "title": "Daily challenge reminder",
            "body": "You haven't logged today's mood yet. It only takes 30 seconds.",
            "icon": "clipboard",
            "action_type": "open_app",
            "action_payload": {"deep_link": "/app"},
            "is_read": True,
            "read_at": a_week_ago + timedelta(hours=3),
            "created_at": a_week_ago,
        },
    ]


async def _resolve_user(
    db,
    user_id: Optional[UUID],
    email: Optional[str],
) -> CompanyUser:
    if user_id is not None:
        stmt = select(CompanyUser).where(
            CompanyUser.id == user_id,
            CompanyUser.is_deleted == False,
        )
    else:
        stmt = select(CompanyUser).where(
            CompanyUser.email == email,
            CompanyUser.is_deleted == False,
        )
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if user is None:
        raise SystemExit(
            f"company_users row not found for "
            f"{'user_id=' + str(user_id) if user_id else 'email=' + str(email)}"
        )
    return user


async def _reset_existing(db, user_id: UUID) -> int:
    now = _utcnow()
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.is_deleted == False,
        )
        .values(is_deleted=True, is_active=False, updated_at=now)
    )
    result = await db.execute(stmt)
    await db.commit()
    return int(result.rowcount or 0)


async def run(
    *,
    user_id: Optional[UUID],
    email: Optional[str],
    reset: bool,
) -> None:
    async with AsyncSessionLocal() as db:
        user = await _resolve_user(db, user_id, email)
        print(f"Seeding notifications for user_id={user.id} email={user.email}")

        if reset:
            cleared = await _reset_existing(db, user.id)
            print(f"  cleared {cleared} existing rows")

        rows = _build_seed_rows(user)
        for payload in rows:
            created_at = payload.pop("created_at")
            read_at = payload.pop("read_at", None)
            entity = Notification(
                user_id=user.id,
                company_id=user.company_id,
                **payload,
            )
            entity.created_at = created_at
            entity.updated_at = created_at
            if read_at is not None:
                entity.read_at = read_at
            db.add(entity)
        await db.commit()
        print(f"  inserted {len(rows)} notifications")
        print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed notifications for one user")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user-id", type=UUID, help="company_users.id (UUID)")
    group.add_argument("--email", type=str, help="company_users.email")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Soft-delete existing notifications for this user before seeding",
    )
    args = parser.parse_args()
    asyncio.run(
        run(
            user_id=args.user_id,
            email=args.email,
            reset=args.reset,
        )
    )


if __name__ == "__main__":
    main()
