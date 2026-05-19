"""Backfill `companies.location_id` from the legacy `companies.location` text.

Reuses `get_or_create_location` so the normalization rules can't drift
between live writes and this one-time backfill. Run AFTER applying
`migrations/locations.sql` and BEFORE `migrations/locations_drop_old_column.sql`.

Usage:
    python -m config_service.app.scripts.backfill_locations
    python -m config_service.app.scripts.backfill_locations --dry-run
"""

import argparse
import asyncio

from sqlalchemy import text

from config_service.app.core.db import AsyncSessionLocal
from config_service.app.services.locations import get_or_create_location


async def run(dry_run: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, location FROM companies "
                    "WHERE location IS NOT NULL AND location <> '' "
                    "  AND location_id IS NULL"
                )
            )
        ).all()

        print(f"Backfilling location_id for {len(rows)} companies "
              f"(dry_run={dry_run})")

        resolved = 0
        skipped_blank = 0
        for company_id, raw_location in rows:
            location_id = await get_or_create_location(raw_location, db)
            if location_id is None:
                skipped_blank += 1
                continue
            await db.execute(
                text(
                    "UPDATE companies SET location_id = :lid "
                    "WHERE id = :cid AND location_id IS NULL"
                ),
                {"lid": location_id, "cid": company_id},
            )
            resolved += 1

        if dry_run:
            await db.rollback()
            print(f"DRY RUN: would have resolved {resolved} rows, "
                  f"{skipped_blank} blank-after-trim skipped. No changes saved.")
            return

        await db.commit()
        print(f"Done. resolved={resolved} skipped_blank={skipped_blank}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve everything in-memory and roll back; report only.",
    )
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
