"""
End-to-end verification for the streak/XP/badge expansion on
POST /config/api/v1/dashboard/challenges/action.

Calls ChallengeActionService.mark_challenge_done directly against the real
database — bypassing FastAPI but exercising the exact code path the endpoint
runs. Creates its own test challenges + KPI windows, runs the 8 tests from
the spec, then rolls back the test fixtures.

Run from repo root:
    venv/Scripts/python.exe config_service/app/scripts/verify_streaks_endpoint.py
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

from sqlalchemy import delete, text

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.db import AsyncSessionLocal
from config_service.app.models.badge_master import BadgeMaster  # noqa: F401
from config_service.app.models.challenge import Challenge
from config_service.app.models.kpi import KPI
from config_service.app.models.kpi_challenge import KPIChallenge
from config_service.app.models.user_badge import UserBadge
from config_service.app.models.user_challenge_completion import UserChallengeCompletion
from config_service.app.models.user_streak import UserStreak
from config_service.app.models.user_xp import UserXp
from config_service.app.schemas.challenge_actions import ChallengeActionRequest
from config_service.app.services.challenge_actions import ChallengeActionService


# Pin the test user. users.id 51 / company_users.email user_2@yopmaail.com is
# already wired to company 6e74b157-fbeb-43ab-9ee8-1eb54ae92976.
TEST_USER_ID = 51
TEST_USER_EMAIL = "user_2@yopmaail.com"

# Picked from `kpis` table — any active KPI works since the spec's KPI-window
# guard only checks the kpi_challenges date range.
TEST_KPI_KEY = uuid.UUID("3274b584-d6d8-4362-87c4-b823e6eb03df")


PASS = "PASS"
FAIL = "FAIL"


def stamp(ok: bool) -> str:
    return PASS if ok else FAIL


async def make_challenge(db, *, name: str, ctype: str, target: int | None, xp: int, company_id) -> uuid.UUID:
    ch = Challenge(
        challenge_key=uuid.uuid4(),
        company_id=company_id,
        name=name,
        challenge_type=ctype,
        target_value=target,
        xp_reward=xp,
        is_daily=True,
        is_active=True,
        is_deleted=False,
    )
    db.add(ch)
    await db.flush()
    return ch.challenge_key


async def make_window(db, *, challenge_key: uuid.UUID, start: date, end: date | None, company_id) -> uuid.UUID:
    kw = KPIChallenge(
        id=uuid.uuid4(),
        kpi_key=TEST_KPI_KEY,
        challenge_key=challenge_key,
        start_date=start,
        end_date=end,
        is_active=True,
        is_deleted=False,
        company_id=company_id,
    )
    db.add(kw)
    await db.flush()
    return kw.id


async def reset_user_state(db, challenge_keys: list[uuid.UUID]):
    """Wipe any prior user_xp / user_streaks / user_badges / completions
    for our test user so each run starts from a known state."""
    await db.execute(delete(UserChallengeCompletion).where(UserChallengeCompletion.user_id == TEST_USER_ID))
    await db.execute(delete(UserStreak).where(UserStreak.user_id == TEST_USER_ID))
    await db.execute(delete(UserBadge).where(UserBadge.user_id == TEST_USER_ID))
    await db.execute(delete(UserXp).where(UserXp.user_id == TEST_USER_ID))
    await db.commit()


async def teardown_fixtures(db, challenge_keys: list[uuid.UUID]):
    if not challenge_keys:
        return
    # Use raw SQL — SQLAlchemy ORM bulk deletes on async sessions can be
    # surprising w.r.t. synchronize_session; raw text is unambiguous.
    keys_csv = ",".join(f"'{k}'" for k in challenge_keys)
    await db.execute(text(f"DELETE FROM user_challenge_completions WHERE challenge_id IN ({keys_csv})"))
    await db.execute(text(f"DELETE FROM user_streaks WHERE challenge_id IN ({keys_csv})"))
    await db.execute(text(f"DELETE FROM kpi_challenges WHERE challenge_key IN ({keys_csv})"))
    await db.execute(text(f"DELETE FROM challenges WHERE challenge_key IN ({keys_csv})"))
    await db.execute(text("DELETE FROM user_badges WHERE user_id = :u"), {"u": TEST_USER_ID})
    await db.execute(text("DELETE FROM user_xp WHERE user_id = :u"), {"u": TEST_USER_ID})
    await db.commit()


async def run_tests() -> tuple[int, int, list[tuple[str, str, str]]]:
    results: list[tuple[str, str, str]] = []
    today = date.today()
    yesterday = today - timedelta(days=1)

    async with AsyncSessionLocal() as setup_db:
        # Look up the test user's company_id so kpi_challenges rows are valid.
        company_row = await setup_db.execute(
            text("SELECT company_id FROM company_users WHERE email = :e AND is_deleted=false"),
            {"e": TEST_USER_EMAIL},
        )
        company_id = company_row.scalar_one()

        # Build six fresh challenges (covers all eligible types + rating + an
        # inactive-window pair for test 7).
        ck_counter = await make_challenge(setup_db, name="VTEST counter", ctype="counter", target=8, xp=25, company_id=company_id)
        ck_toggle  = await make_challenge(setup_db, name="VTEST toggle",  ctype="toggle",  target=1, xp=25, company_id=company_id)
        ck_choice  = await make_challenge(setup_db, name="VTEST choice",  ctype="choice",  target=None, xp=25, company_id=company_id)
        ck_multi   = await make_challenge(setup_db, name="VTEST multi",   ctype="multi",   target=None, xp=25, company_id=company_id)
        ck_timer   = await make_challenge(setup_db, name="VTEST timer",   ctype="timer",   target=120, xp=25, company_id=company_id)
        ck_rating  = await make_challenge(setup_db, name="VTEST rating",  ctype="rating",  target=None, xp=10, company_id=company_id)
        ck_offwindow = await make_challenge(setup_db, name="VTEST offwindow", ctype="counter", target=5, xp=25, company_id=company_id)

        # Active windows for the first 6; an expired window for the 7th.
        await make_window(setup_db, challenge_key=ck_counter, start=today - timedelta(days=30), end=today + timedelta(days=30), company_id=company_id)
        await make_window(setup_db, challenge_key=ck_toggle,  start=today - timedelta(days=30), end=today + timedelta(days=30), company_id=company_id)
        await make_window(setup_db, challenge_key=ck_choice,  start=today - timedelta(days=30), end=today + timedelta(days=30), company_id=company_id)
        await make_window(setup_db, challenge_key=ck_multi,   start=today - timedelta(days=30), end=today + timedelta(days=30), company_id=company_id)
        await make_window(setup_db, challenge_key=ck_timer,   start=today - timedelta(days=30), end=today + timedelta(days=30), company_id=company_id)
        await make_window(setup_db, challenge_key=ck_rating,  start=today - timedelta(days=30), end=today + timedelta(days=30), company_id=company_id)
        await make_window(setup_db, challenge_key=ck_offwindow, start=today - timedelta(days=30), end=today - timedelta(days=10), company_id=company_id)

        await setup_db.commit()

    all_challenge_keys = [ck_counter, ck_toggle, ck_choice, ck_multi, ck_timer, ck_rating, ck_offwindow]

    # ---------------- helpers ----------------

    async def call(challenge_id, **kwargs):
        async with AsyncSessionLocal() as db:
            svc = ChallengeActionService(db)
            return await svc.mark_challenge_done(
                user_id=TEST_USER_ID,
                user_email=TEST_USER_EMAIL,
                payload=ChallengeActionRequest(challenge_id=challenge_id, **kwargs),
            )

    async def force_streak(challenge_id, *, current, longest, last_date):
        """Seed user_streaks with a known prior state."""
        async with AsyncSessionLocal() as db:
            await db.execute(delete(UserStreak).where(
                UserStreak.user_id == TEST_USER_ID,
                UserStreak.challenge_id == challenge_id,
            ))
            db.add(UserStreak(
                user_id=TEST_USER_ID,
                challenge_id=challenge_id,
                current_streak=current,
                longest_streak=longest,
                last_completion_date=last_date,
            ))
            await db.commit()

    async def force_xp(total_xp):
        async with AsyncSessionLocal() as db:
            await db.execute(delete(UserXp).where(UserXp.user_id == TEST_USER_ID))
            # current_level/label here are stale on purpose: we want to verify
            # the service recomputes level on update.
            db.add(UserXp(
                user_id=TEST_USER_ID,
                total_xp=total_xp,
                xp_this_week=0,
                current_level=1,
                level_label="Seedling",
            ))
            await db.commit()

    async def fetch_streak(challenge_id):
        async with AsyncSessionLocal() as db:
            row = await db.execute(text(
                "SELECT current_streak, longest_streak, last_completion_date "
                "FROM user_streaks WHERE user_id=:u AND challenge_id=:c"
            ), {"u": TEST_USER_ID, "c": str(challenge_id)})
            return row.first()

    async def count_completions(challenge_id):
        async with AsyncSessionLocal() as db:
            row = await db.execute(text(
                "SELECT COUNT(*) FROM user_challenge_completions "
                "WHERE user_id=:u AND challenge_id=:c"
            ), {"u": TEST_USER_ID, "c": str(challenge_id)})
            return row.scalar_one()

    async def count_user_badge_for(streak_value):
        async with AsyncSessionLocal() as db:
            row = await db.execute(text(
                "SELECT COUNT(*) FROM user_badges ub "
                "JOIN badges_master bm ON bm.id = ub.badge_id "
                "WHERE ub.user_id=:u AND bm.trigger_type='streak' AND bm.trigger_value=:v"
            ), {"u": TEST_USER_ID, "v": streak_value})
            return row.scalar_one()

    # =========================================================================
    # Test 1 — counter, first completion -> streak status = "new"
    # =========================================================================
    async with AsyncSessionLocal() as db:
        await reset_user_state(db, all_challenge_keys)
    res = await call(ck_counter, value_logged=3)
    ok = (
        res.streak is not None
        and res.streak.current_streak == 1
        and res.streak.streak_status == "new"
    )
    results.append(("Test 1 counter first completion", stamp(ok), f"streak={res.streak}"))

    # =========================================================================
    # Test 2 — toggle consecutive day -> streak status = "incremented"
    # =========================================================================
    async with AsyncSessionLocal() as db:
        await reset_user_state(db, all_challenge_keys)
    await force_streak(ck_toggle, current=3, longest=5, last_date=yesterday)
    res = await call(ck_toggle, toggle_value=True)
    ok = (
        res.streak is not None
        and res.streak.current_streak == 4
        and res.streak.longest_streak == 5
        and res.streak.streak_status == "incremented"
    )
    results.append(("Test 2 toggle consecutive day", stamp(ok), f"streak={res.streak}"))

    # =========================================================================
    # Test 3 — choice broken streak -> streak status = "reset", longest unchanged
    # =========================================================================
    async with AsyncSessionLocal() as db:
        await reset_user_state(db, all_challenge_keys)
    await force_streak(ck_choice, current=4, longest=10, last_date=today - timedelta(days=5))
    res = await call(ck_choice, choice_value=1)
    ok = (
        res.streak is not None
        and res.streak.current_streak == 1
        and res.streak.longest_streak == 10
        and res.streak.streak_status == "reset"
    )
    results.append(("Test 3 choice broken streak", stamp(ok), f"streak={res.streak}"))

    # =========================================================================
    # Test 4 — duplicate same day (toggle) -> 409 "Already completed today"
    # =========================================================================
    async with AsyncSessionLocal() as db:
        await reset_user_state(db, all_challenge_keys)
    await call(ck_toggle, toggle_value=True)
    streak_before = await fetch_streak(ck_toggle)
    try:
        await call(ck_toggle, toggle_value=True)
        ok = False
        msg = "should have raised"
    except BusinessException as e:
        msg = e.message
        ok = "Already completed today" in msg and e.status_code == 409
    streak_after = await fetch_streak(ck_toggle)
    ok = ok and streak_before == streak_after
    results.append(("Test 4 duplicate same day blocked", stamp(ok), f"err='{msg}', streak_unchanged={streak_before == streak_after}"))

    # =========================================================================
    # Test 5 — rating: no streak row, no badge, XP still awarded
    # =========================================================================
    async with AsyncSessionLocal() as db:
        await reset_user_state(db, all_challenge_keys)
    res = await call(ck_rating, rating_value=4)
    completions = await count_completions(ck_rating)
    streak_row = await fetch_streak(ck_rating)
    ok = (
        res.streak is None
        and res.badge_earned is False
        and res.badge is None
        and completions == 1
        and streak_row is None
        and res.xp is not None
        and res.xp.total_xp >= 10
    )
    results.append(("Test 5 rating skips streak/badge but writes completion+XP", stamp(ok),
                    f"streak={res.streak}, xp.total_xp={res.xp.total_xp if res.xp else None}, streak_row={streak_row}"))

    # =========================================================================
    # Test 6 — streak milestone -> badge awarded
    #   Set current=6, last=yesterday, complete today => current_streak=7, awards STREAK_7.
    # =========================================================================
    async with AsyncSessionLocal() as db:
        await reset_user_state(db, all_challenge_keys)
    await force_streak(ck_timer, current=6, longest=6, last_date=yesterday)
    res = await call(ck_timer, timer_seconds=120)
    ok = (
        res.streak is not None
        and res.streak.current_streak == 7
        and res.badge_earned is True
        and res.badge is not None
        and res.badge.badge_key == "STREAK_7"
    )
    badge_count = await count_user_badge_for(7)
    ok = ok and badge_count == 1
    results.append(("Test 6 milestone awards STREAK_7 badge", stamp(ok),
                    f"badge={res.badge.badge_key if res.badge else None}, user_badges_for_7={badge_count}"))

    # =========================================================================
    # Test 7 — inactive KPI window -> 400, nothing written
    # =========================================================================
    async with AsyncSessionLocal() as db:
        await reset_user_state(db, all_challenge_keys)
    try:
        await call(ck_offwindow, value_logged=2)
        ok = False
        msg = "should have raised"
    except BusinessException as e:
        msg = e.message
        ok = "not active" in msg.lower() and e.status_code == 400
    completions = await count_completions(ck_offwindow)
    streak_row = await fetch_streak(ck_offwindow)
    ok = ok and completions == 0 and streak_row is None
    results.append(("Test 7 inactive KPI window blocked", stamp(ok),
                    f"err='{msg}', completions={completions}, streak={streak_row}"))

    # =========================================================================
    # Test 8 — level up at 100 XP boundary
    #   Seed total_xp=98 stale at level 1, earn 25 XP from a toggle (full XP
    #   only granted when the toggle is on — a counter at value=3/target=8
    #   would award a partial 9 XP), expect total_xp=123, current_level=2,
    #   level_label='Sapling', level_up=true.
    # =========================================================================
    async with AsyncSessionLocal() as db:
        await reset_user_state(db, all_challenge_keys)
    await force_xp(98)
    res = await call(ck_toggle, toggle_value=True)
    ok = (
        res.xp is not None
        and res.xp.total_xp == 123
        and res.xp.current_level == 2
        and res.xp.level_label == "Sapling"
        and res.xp.level_up is True
    )
    results.append(("Test 8 level up across Sapling boundary", stamp(ok),
                    f"xp={res.xp.model_dump() if res.xp else None}"))

    # ---------------- teardown ----------------
    async with AsyncSessionLocal() as db:
        await teardown_fixtures(db, all_challenge_keys)

    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = sum(1 for _, s, _ in results if s == FAIL)
    return passed, failed, results


def main():
    passed, failed, results = asyncio.run(run_tests())
    width = max(len(name) for name, _, _ in results)
    print()
    print("=" * (width + 60))
    for name, status, detail in results:
        print(f"{status:4}  {name.ljust(width)}  | {detail}")
    print("=" * (width + 60))
    print(f"Summary: {passed} passed, {failed} failed (of {passed + failed})")
    raise SystemExit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
