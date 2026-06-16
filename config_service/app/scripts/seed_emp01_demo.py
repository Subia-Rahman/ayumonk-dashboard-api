from __future__ import annotations
"""
Demo gamification seed for user EMP01.

EMP01 (users.id=50, "Chintan", email rahman.subia@gmail.com, company
6e74b157-fbeb-43ab-9ee8-1eb54ae92976) is the showcase account. This script
backfills enough activity to populate every dashboard surface meaningfully:

    * Current 7-day streak on "session 5 may challenge"
    * longest_streak=12 on that challenge (narrative: previous best)
    * Completion rows for the last ~15 days across 5 different challenges
    * user_xp at Level 2 "Sapling"
    * 5 badges earned (2 streak milestones + 3 KPI bronze tiers)

Defaults to additive — aborts if any planned (user, challenge, date) tuple
already exists. Use --wipe to clear EMP01's gamification state first.

Run:
    set PYTHONPATH=. && python config_service\\app\\scripts\\seed_emp01_demo.py --wipe
    # or without writing anything:
    set PYTHONPATH=. && python config_service\\app\\scripts\\seed_emp01_demo.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import bindparam, text

from config_service.app.core.db import AsyncSessionLocal


EMP01_USER_ID = 50
EMP01_EMAIL = "rahman.subia@gmail.com"
EMP01_COMPANY_ID = "6e74b157-fbeb-43ab-9ee8-1eb54ae92976"

# Challenge name -> challenge_key (re-resolved at runtime so a rename doesn't
# break the seed silently). XP values mirror challenges.xp_reward.
CHALLENGES = {
    "session 5 may challenge": {"type": "toggle",  "xp": 2,  "target": 1,  "value": 1},
    "challenge 2":             {"type": "toggle",  "xp": 20, "target": 0,  "value": 1},
    "MY challenge":            {"type": "timer",   "xp": 20, "target": 10, "value": 10},
    "May 5 session challenge": {"type": "counter", "xp": 1,  "target": 0,  "value": 1},
    "Drink water":             {"type": "counter", "xp": 5,  "target": 12, "value": 12},
}

# Badges to award after seeding (badge_key -> chosen earned_at offset).
BADGES_TO_AWARD = [
    "STREAK_3",
    "STREAK_7",
    "PHYSICAL_VITALITY_BRONZE",
    "COGNITIVE_FOCUS_BRONZE",
    "KPI0904_0202_BRONZE",
]


def plan_completions(today: date) -> list[dict]:
    """
    Returns a list of completion specs. Each spec is:
      {challenge: str, day: date, value: int, xp: int}
    """
    plan: list[dict] = []

    # --- A. "session 5 may challenge" (toggle, +2 XP, Physical Vitality KPI)
    # 12-day broken streak from D-29 to D-18 (the longest_streak narrative).
    for offset in range(29, 17, -1):
        plan.append({
            "challenge": "session 5 may challenge",
            "day": today - timedelta(days=offset),
            "value": 1, "xp": 2,
        })
    # 7-day current streak D-6 .. D-0 (today).
    for offset in range(6, -1, -1):
        plan.append({
            "challenge": "session 5 may challenge",
            "day": today - timedelta(days=offset),
            "value": 1, "xp": 2,
        })

    # --- B. "challenge 2" (toggle, +20 XP) — last 5 days
    for offset in range(4, -1, -1):
        plan.append({
            "challenge": "challenge 2",
            "day": today - timedelta(days=offset),
            "value": 1, "xp": 20,
        })

    # --- C. "MY challenge" (timer, +20 XP) — last 4 days
    for offset in range(3, -1, -1):
        plan.append({
            "challenge": "MY challenge",
            "day": today - timedelta(days=offset),
            "value": 10, "xp": 20,
        })

    # --- D. "May 5 session challenge" (counter, +1 XP) — 7 spaced days
    # (drives Cognitive Focus Bronze: needs ≥7 completions in that KPI).
    for offset in [12, 10, 8, 5, 3, 1, 0]:
        plan.append({
            "challenge": "May 5 session challenge",
            "day": today - timedelta(days=offset),
            "value": 1, "xp": 1,
        })

    # --- E. "Drink water" (counter, +5 XP at target=12) — 7 spaced days
    # (drives KPI0904_0202 Bronze).
    for offset in [11, 9, 7, 4, 2, 1, 0]:
        plan.append({
            "challenge": "Drink water",
            "day": today - timedelta(days=offset),
            "value": 12, "xp": 5,
        })

    return plan


def expected_streaks(today: date) -> list[dict]:
    """user_streaks rows to upsert."""
    return [
        # 7-day current streak, longest 12 (story: previously hit 12, broke
        # it, rebuilt to 7).
        {"challenge": "session 5 may challenge",
         "current": 7, "longest": 12, "last": today},
        # 5-day current streak on challenge 2.
        {"challenge": "challenge 2",
         "current": 5, "longest": 5, "last": today},
        # 4-day current streak on MY challenge.
        {"challenge": "MY challenge",
         "current": 4, "longest": 4, "last": today},
        # Counters get streak rows too (one entry incremented per day they're
        # logged). The spaced pattern means "reset" — current_streak=1, last
        # day = today.
        {"challenge": "May 5 session challenge",
         "current": 1, "longest": 2, "last": today},
        {"challenge": "Drink water",
         "current": 3, "longest": 3, "last": today},  # last 3 spaced offsets [2,1,0] are consecutive
    ]


async def resolve_challenge_keys(db) -> dict[str, uuid.UUID]:
    stmt = text("""
        SELECT challenge_key, name
        FROM challenges
        WHERE company_id = :cid AND is_deleted = false
          AND name IN :names
    """).bindparams(bindparam("names", expanding=True))
    res = await db.execute(stmt, {"cid": EMP01_COMPANY_ID,
                                  "names": list(CHALLENGES.keys())})
    return {name: key for key, name in res.fetchall()}


async def resolve_badge_ids(db) -> dict[str, uuid.UUID]:
    stmt = text("""
        SELECT id, badge_key FROM badges_master
        WHERE badge_key IN :keys AND is_deleted = false
    """).bindparams(bindparam("keys", expanding=True))
    res = await db.execute(stmt, {"keys": list(BADGES_TO_AWARD)})
    return {bk: bid for bid, bk in res.fetchall()}


async def run(*, wipe: bool, dry_run: bool) -> int:
    today = date.today()
    plan = plan_completions(today)
    streaks = expected_streaks(today)

    print(f"Today: {today}    User: EMP01 (id={EMP01_USER_ID})")
    print(f"Initial plan: {len(plan)} completion rows, {len(streaks)} streak "
          f"rows, {len(BADGES_TO_AWARD)} badge rows")

    async with AsyncSessionLocal() as db:
        # Resolve foreign keys
        ch_keys = await resolve_challenge_keys(db)
        missing = [n for n in CHALLENGES if n not in ch_keys]
        if missing:
            print(f"\nWARN: {len(missing)} challenge(s) not found "
                  f"(missing or is_deleted=true) — their plan rows will be "
                  f"skipped: {missing}", file=sys.stderr)
            # Diagnostic: show what IS available so the user can adjust
            # the CHALLENGES dict if they want richer demo data.
            available = (await db.execute(text("""
                SELECT name, challenge_type
                FROM challenges
                WHERE company_id = :cid AND is_deleted = false
                ORDER BY name
            """), {"cid": EMP01_COMPANY_ID})).fetchall()
            print(f"Available active challenges in company {EMP01_COMPANY_ID}:",
                  file=sys.stderr)
            for nm, ct in available:
                print(f"  - {nm}  ({ct})", file=sys.stderr)
        if not ch_keys:
            print("ERROR: no planned challenges exist for this company — "
                  "edit CHALLENGES at the top of this script to match what's "
                  "available above.", file=sys.stderr)
            return 1
        # Filter the plan and streak rows down to challenges that resolved.
        plan = [p for p in plan if p["challenge"] in ch_keys]
        streaks = [s for s in streaks if s["challenge"] in ch_keys]
        total_xp = sum(p["xp"] for p in plan)
        print(f"\nAfter filtering missing challenges: {len(plan)} completion "
              f"rows, {len(streaks)} streak rows, total XP {total_xp}")
        badge_ids = await resolve_badge_ids(db)
        missing_badges = [b for b in BADGES_TO_AWARD if b not in badge_ids]
        if missing_badges:
            print(f"ERROR: badges not seeded yet: {missing_badges}", file=sys.stderr)
            print("Run badges_master migration and seed_kpi_badges.py first.", file=sys.stderr)
            return 1

        if dry_run:
            print("\nSample of planned completions:")
            for p in plan[:5] + plan[-3:]:
                print(f"  {p['day']}  {p['challenge']:<28}  value={p['value']}  +{p['xp']} XP")
            print("\nPlanned streaks:")
            for s in streaks:
                print(f"  {s['challenge']:<28}  current={s['current']}  longest={s['longest']}  last={s['last']}")
            print("\nPlanned badges:")
            for b in BADGES_TO_AWARD:
                print(f"  {b}")
            print("\nDRY RUN — no writes.")
            return 0

        # Conflict check (only if not wiping)
        if not wipe:
            for p in plan:
                conflict = (await db.execute(text("""
                    SELECT 1 FROM user_challenge_completions
                    WHERE user_id = :u AND challenge_id = :c AND completion_date = :d
                """), {"u": EMP01_USER_ID, "c": str(ch_keys[p["challenge"]]),
                       "d": p["day"]})).first()
                if conflict:
                    print(f"ERROR: existing completion blocks plan: "
                          f"{p['challenge']} on {p['day']}. Rerun with --wipe.",
                          file=sys.stderr)
                    return 2

        if wipe:
            print("\nWIPING EMP01 gamification state...")
            await db.execute(text("DELETE FROM user_challenge_completions WHERE user_id = :u"), {"u": EMP01_USER_ID})
            await db.execute(text("DELETE FROM user_streaks WHERE user_id = :u"), {"u": EMP01_USER_ID})
            await db.execute(text("DELETE FROM user_xp WHERE user_id = :u"), {"u": EMP01_USER_ID})
            await db.execute(text("DELETE FROM user_badges WHERE user_id = :u"), {"u": EMP01_USER_ID})
            await db.commit()

        # 1. Insert completions. The existing user_challenge_completions
        # table has NOT NULL audit columns with no DB-side defaults (the
        # SQLAlchemy AuditMixin applies them Python-side, which raw INSERTs
        # bypass), so we set them explicitly.
        for p in plan:
            await db.execute(text("""
                INSERT INTO user_challenge_completions
                    (id, user_id, challenge_id, company_id, completion_date,
                     value_logged, xp_earned,
                     created_at, updated_at, is_active, is_deleted)
                VALUES
                    (gen_random_uuid(), :u, :c, :co, :d, :v, :xp,
                     NOW(), NOW(), TRUE, FALSE)
            """), {
                "u": EMP01_USER_ID, "c": str(ch_keys[p["challenge"]]),
                "co": EMP01_COMPANY_ID, "d": p["day"],
                "v": p["value"], "xp": p["xp"],
            })

        # 2. Upsert user_streaks
        for s in streaks:
            await db.execute(text("""
                INSERT INTO user_streaks
                    (id, user_id, challenge_id, current_streak, longest_streak,
                     last_completion_date)
                VALUES (gen_random_uuid(), :u, :c, :cur, :lng, :last)
                ON CONFLICT (user_id, challenge_id) DO UPDATE SET
                    current_streak = EXCLUDED.current_streak,
                    longest_streak = EXCLUDED.longest_streak,
                    last_completion_date = EXCLUDED.last_completion_date,
                    updated_at = NOW()
            """), {
                "u": EMP01_USER_ID, "c": str(ch_keys[s["challenge"]]),
                "cur": s["current"], "lng": s["longest"], "last": s["last"],
            })

        # 3. user_xp aggregate — sum of completion XP. xp_this_week is XP
        # from completions in the last 7 days only.
        week_xp = sum(p["xp"] for p in plan if (today - p["day"]).days <= 6)
        level, label = _level_for_xp(total_xp)
        await db.execute(text("""
            INSERT INTO user_xp (id, user_id, total_xp, xp_this_week,
                                 current_level, level_label)
            VALUES (gen_random_uuid(), :u, :t, :w, :l, :lab)
            ON CONFLICT (user_id) DO UPDATE SET
                total_xp = EXCLUDED.total_xp,
                xp_this_week = EXCLUDED.xp_this_week,
                current_level = EXCLUDED.current_level,
                level_label = EXCLUDED.level_label,
                updated_at = NOW()
        """), {"u": EMP01_USER_ID, "t": total_xp, "w": week_xp,
               "l": level, "lab": label})

        # 4. Award badges
        for bk in BADGES_TO_AWARD:
            await db.execute(text("""
                INSERT INTO user_badges (id, user_id, badge_id)
                VALUES (gen_random_uuid(), :u, :b)
                ON CONFLICT (user_id, badge_id) DO NOTHING
            """), {"u": EMP01_USER_ID, "b": str(badge_ids[bk])})

        await db.commit()

        print(f"\nSeed applied:")
        print(f"  completions:        {len(plan)}")
        print(f"  total_xp:           {total_xp}    (Level {level} {label})")
        print(f"  xp_this_week:       {week_xp}")
        print(f"  streaks upserted:   {len(streaks)}")
        print(f"  badges awarded:     {len(BADGES_TO_AWARD)}")
        return 0


def _level_for_xp(xp: int) -> tuple[int, str]:
    if xp >= 2000: return 6, "Banyan Legend"
    if xp >= 1000: return 5, "Banyan Tree"
    if xp >= 600:  return 4, "Banyan Sapling"
    if xp >= 300:  return 3, "Tree"
    if xp >= 100:  return 2, "Sapling"
    return 1, "Seedling"


def main():
    p = argparse.ArgumentParser(description="Demo gamification seed for EMP01.")
    p.add_argument("--wipe", action="store_true",
                   help="Delete EMP01's existing gamification state before seeding.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the plan without writing anything.")
    args = p.parse_args()
    sys.exit(asyncio.run(run(wipe=args.wipe, dry_run=args.dry_run)))


if __name__ == "__main__":
    main()
