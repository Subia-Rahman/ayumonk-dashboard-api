"""
Seed per-KPI tier badges for a company.

For each active KPI belonging to the given company, inserts three rows into
badges_master with trigger_type='kpi_completions' and ascending thresholds
(Bronze / Silver / Gold). Re-runnable — uses ON CONFLICT (badge_key) DO
NOTHING so existing rows are preserved unchanged.

Threshold defaults: 7 / 30 / 100 completions. Override via flags.

Icon defaults: every tier gets icon='medal'. The award logic doesn't care
about the icon string; it's only for display. Have your platform admin edit
icons via the admin UI (or another seed pass) once they decide on assets.

Usage (run from repo root):

    PYTHONPATH=. venv/Scripts/python.exe \\
        config_service/app/scripts/seed_kpi_badges.py \\
        --company-id 6e74b157-fbeb-43ab-9ee8-1eb54ae92976

Optional flags:
    --bronze 7 --silver 30 --gold 100   threshold overrides (must ascend)
    --dry-run                            print what would be inserted, no writes
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid

from sqlalchemy import text

from config_service.app.core.db import AsyncSessionLocal


# (tier_key, display_label) — tier_key is stored in badges_master.level and
# is also used as the badge_key suffix.
TIERS = [
    ("bronze", "Bronze"),
    ("silver", "Silver"),
    ("gold",   "Gold"),
]
DEFAULT_THRESHOLDS = {"bronze": 7, "silver": 30, "gold": 100}
DEFAULT_ICON = "medal"


def slugify(name: str) -> str:
    """KPI display_name → uppercase underscore slug for badge_key."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", name or "").strip("_").upper()
    return s or "KPI"


async def run(company_id: uuid.UUID, thresholds: dict[str, int], dry_run: bool,
              actor_user_id: int | None) -> int:
    async with AsyncSessionLocal() as db:
        # ----- 1. validate company ------------------------------------------
        company = (
            await db.execute(
                text(
                    "SELECT id, company_name FROM companies "
                    "WHERE id = :id AND is_deleted = false"
                ),
                {"id": str(company_id)},
            )
        ).first()
        if not company:
            print(f"ERROR: company {company_id} not found or deleted", file=sys.stderr)
            return 2
        print(f"Company: {company.company_name}  ({company.id})")

        # ----- 2. fetch active KPIs -----------------------------------------
        kpis = (
            await db.execute(
                text(
                    "SELECT kpi_key, display_name FROM kpis "
                    "WHERE company_id = :cid "
                    "  AND is_deleted = false "
                    "  AND is_active = true "
                    "ORDER BY display_name"
                ),
                {"cid": str(company_id)},
            )
        ).fetchall()

        if not kpis:
            print(f"No active KPIs for company {company_id} — nothing to seed.")
            return 0
        print(f"Active KPIs: {len(kpis)}")

        # ----- 3. plan rows -------------------------------------------------
        # Detect badge_key collisions caused by duplicate KPI display_names
        # within the same company. Those collisions would silently skip later
        # tiers, which is hard to debug, so we report them up-front.
        slug_to_kpi: dict[str, list[str]] = {}
        for kpi_key, display_name in kpis:
            slug_to_kpi.setdefault(slugify(display_name), []).append(display_name)
        for slug, names in slug_to_kpi.items():
            if len(names) > 1:
                print(f"WARN: slug '{slug}' is produced by multiple KPIs: {names!r} — only the first will get a badge row.", file=sys.stderr)

        planned: list[dict] = []
        for kpi_key, display_name in kpis:
            slug = slugify(display_name)
            for tier_key, tier_label in TIERS:
                planned.append({
                    # Generate id Python-side so the script doesn't depend on
                    # the pgcrypto extension (gen_random_uuid()) being
                    # installed in the target database.
                    "id":            str(uuid.uuid4()),
                    "badge_key":     f"{slug}_{tier_key.upper()}",
                    "label":         f"{display_name} {tier_label}",
                    "icon":          DEFAULT_ICON,
                    "level":         tier_key,
                    "trigger_type":  "kpi_completions",
                    "trigger_value": thresholds[tier_key],
                    "kpi_key":       str(kpi_key),
                })

        print(f"\nPlanned rows: {len(planned)}")
        for r in planned:
            print(
                f"  {r['badge_key']:<42}  {r['label']:<40}  "
                f"tier={r['level']:<6}  trigger>={r['trigger_value']:>4}"
            )

        if dry_run:
            print("\nDRY RUN — no rows inserted.")
            return 0

        # ----- 4. insert (idempotent on badge_key) --------------------------
        # Audit columns are populated explicitly so the seed is portable
        # across environments where badges_master may have been created
        # without DB-side defaults (the SQLAlchemy AuditMixin applies them
        # Python-side, which raw INSERTs bypass). created_by / updated_by
        # carry the seeding admin's user_id when --actor-user-id is passed;
        # otherwise NULL = anonymous system seed.
        inserted = skipped = 0
        for r in planned:
            params = {**r, "actor": actor_user_id}
            res = await db.execute(
                text(
                    """
                    INSERT INTO badges_master
                        (id, badge_key, label, icon, level,
                         trigger_type, trigger_value, kpi_key,
                         created_at, updated_at,
                         created_by, updated_by,
                         is_active, is_deleted)
                    VALUES
                        (:id, :badge_key, :label, :icon, :level,
                         :trigger_type, :trigger_value, :kpi_key,
                         NOW(), NOW(),
                         :actor, :actor,
                         TRUE, FALSE)
                    ON CONFLICT (badge_key) DO NOTHING
                    RETURNING id
                    """
                ),
                params,
            )
            if res.first() is not None:
                inserted += 1
            else:
                skipped += 1
        await db.commit()

        print(f"\nInserted: {inserted}    Skipped (already existed): {skipped}")
        return 0


def main():
    p = argparse.ArgumentParser(description="Seed per-KPI tier badges for a company.")
    p.add_argument("--company-id", required=True, type=uuid.UUID,
                   help="UUID of the company whose KPIs should get tier badges.")
    p.add_argument("--bronze", type=int, default=DEFAULT_THRESHOLDS["bronze"],
                   help=f"Bronze trigger threshold (default {DEFAULT_THRESHOLDS['bronze']}).")
    p.add_argument("--silver", type=int, default=DEFAULT_THRESHOLDS["silver"],
                   help=f"Silver trigger threshold (default {DEFAULT_THRESHOLDS['silver']}).")
    p.add_argument("--gold",   type=int, default=DEFAULT_THRESHOLDS["gold"],
                   help=f"Gold trigger threshold (default {DEFAULT_THRESHOLDS['gold']}).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the plan without writing anything.")
    p.add_argument("--actor-user-id", type=int, default=None,
                   help="users.id to stamp into created_by/updated_by. "
                        "Omit for an anonymous system seed (NULL).")
    args = p.parse_args()

    if not (0 < args.bronze < args.silver < args.gold):
        print("ERROR: thresholds must be positive and strictly ascending "
              "(0 < bronze < silver < gold).", file=sys.stderr)
        sys.exit(1)

    thresholds = {"bronze": args.bronze, "silver": args.silver, "gold": args.gold}
    sys.exit(asyncio.run(run(args.company_id, thresholds, args.dry_run,
                             args.actor_user_id)))


if __name__ == "__main__":
    main()
