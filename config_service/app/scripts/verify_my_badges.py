from __future__ import annotations
"""
Smoke test for GET /dashboard/me/badges (service layer, no FastAPI client).

Calls BadgesService.list_for_user directly:
  1. baseline — confirm response shape and earned_count=0 for a clean user
  2. award STREAK_3 manually -> response reflects it as earned=True
  3. confirm earned tile appears in the right place; other tiles still locked

Run:
    PYTHONPATH=. venv/Scripts/python.exe \\
        config_service/app/scripts/verify_my_badges.py
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from config_service.app.core.db import AsyncSessionLocal
from config_service.app.services.badges import BadgesService


TEST_USER_ID = 51
TEST_USER_EMAIL = "user_2@yopmaail.com"


async def reset_user_badges():
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM user_badges WHERE user_id = :u"), {"u": TEST_USER_ID})
        await db.commit()


async def award_streak_3():
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO user_badges (user_id, badge_id) "
            "SELECT :u, id FROM badges_master WHERE badge_key = 'STREAK_3'"
        ), {"u": TEST_USER_ID})
        await db.commit()


async def list_badges():
    async with AsyncSessionLocal() as db:
        return await BadgesService(db).list_for_user(
            user_id=TEST_USER_ID, user_email=TEST_USER_EMAIL
        )


async def main() -> int:
    failures = 0

    await reset_user_badges()
    baseline = await list_badges()
    print(f"Baseline: total={baseline.total_count}, earned={baseline.earned_count}")
    if baseline.earned_count != 0:
        print("  FAIL: expected earned_count=0 after reset")
        failures += 1

    sample = baseline.badges[:5] + baseline.badges[-3:]
    print("\nFirst 5 + last 3 tiles:")
    for b in sample:
        kpi = b.kpi_display_name or "(global)"
        print(f"  {b.badge_key:<32}  kpi={kpi:<28}  tier={b.level:<7}  "
              f"trigger={b.trigger_type}/{b.trigger_value}  earned={b.earned}")

    await award_streak_3()
    after = await list_badges()
    print(f"\nAfter awarding STREAK_3: earned={after.earned_count}/{after.total_count}")
    if after.earned_count != 1:
        print("  FAIL: expected earned_count=1")
        failures += 1

    streak3 = next((b for b in after.badges if b.badge_key == "STREAK_3"), None)
    if not streak3:
        print("  FAIL: STREAK_3 missing from response")
        failures += 1
    elif not streak3.earned or streak3.earned_at is None:
        print(f"  FAIL: STREAK_3 not marked earned: {streak3}")
        failures += 1
    else:
        print(f"  PASS: STREAK_3 marked earned at {streak3.earned_at}")

    others_still_locked = all(
        not b.earned for b in after.badges if b.badge_key != "STREAK_3"
    )
    if not others_still_locked:
        print("  FAIL: badges other than STREAK_3 also marked earned")
        failures += 1
    else:
        print(f"  PASS: {after.total_count - 1} other badges still locked")

    # Confirm visibility filter — no returned badge belongs to a KPI from
    # another company. Compare the set the service returned against the set
    # of "foreign" KPI badges in the DB.
    returned_keys = {b.badge_key for b in after.badges}
    async with AsyncSessionLocal() as db:
        foreign = (await db.execute(text("""
            SELECT bm.badge_key
            FROM badges_master bm
            JOIN kpis k ON k.kpi_key = bm.kpi_key
            WHERE k.company_id <> (SELECT company_id FROM company_users WHERE email = :e)
              AND bm.is_deleted = false AND bm.is_active = true
        """), {"e": TEST_USER_EMAIL})).scalars().all()
    leaked = returned_keys.intersection(foreign)
    if leaked:
        print(f"  FAIL: visibility leak — foreign-company badges visible: {sorted(leaked)}")
        failures += 1
    else:
        print(f"  PASS: no cross-company KPI badges leaked into response "
              f"({len(foreign)} foreign badges exist in DB, none returned)")

    await reset_user_badges()

    print()
    if failures:
        print(f"FAILED ({failures} issue(s))")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
