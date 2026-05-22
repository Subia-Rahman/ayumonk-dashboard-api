"""Seed default CXO metric mappings for one or every existing company.

Reads the platform defaults defined in
``config_service.app.services.cxo_seeder`` (Productivity weights,
Absenteeism weights+thresholds, Engagement signal weights) and upserts
``cxo_metric_kpi_mapping`` / ``cxo_metric_signal_mapping`` rows. Mirrors
the behaviour of ``POST /config/api/v1/admin/cxo-metrics/{code}/reset``
but in batch form.

Prerequisites:
  * ``cxo_metric_master`` is already seeded (run
    ``config_service/app/scripts/migrations/seed_cxo_metric_master.sql``
    or ``cxo_metrics_up.sql``).
  * Each target company has the methodology KPIs already created in
    ``kpis`` (Sleep, Stress, Energy, Pain, Activity, Digestion). Missing
    KPIs are logged and listed in the seeder's SeedResult.skipped_kpis.

Usage:
    # All companies
    python -m config_service.app.scripts.seed_cxo_default_mappings

    # One company
    python -m config_service.app.scripts.seed_cxo_default_mappings \\
        --company-id 6f1a4f2e-8a37-4f7d-bf4d-bcb0c4d5e9c1

    # Only one metric across all companies
    python -m config_service.app.scripts.seed_cxo_default_mappings \\
        --metric PRODUCTIVITY

  ``--actor-user-id`` (default 0) populates created_by/updated_by + the
  audit-log user_id.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from config_service.app.core.db import AsyncSessionLocal
from config_service.app.models.company import Company
from config_service.app.services.cxo_seeder import (
    ALL_METRIC_CODES,
    seed_default_cxo_mappings,
)


async def run(
    *,
    company_id: UUID | None,
    metric_codes: list[str] | None,
    actor_user_id: int,
) -> None:
    async with AsyncSessionLocal() as db:
        targets = await _resolve_companies(db, company_id)
        if not targets:
            print("No matching companies found — nothing to do.")
            return

        print(
            f"Seeding {len(targets)} companies "
            f"(metrics={metric_codes or list(ALL_METRIC_CODES)})"
        )

        for cid in targets:
            try:
                result = await seed_default_cxo_mappings(
                    db,
                    company_id=cid,
                    actor_user_id=actor_user_id,
                    metric_codes=metric_codes,
                )
                await db.commit()
                line = (
                    f"  company={cid} | seeded={result.seeded} | "
                    f"skipped_kpis={result.skipped_kpis} | errors={result.errors}"
                )
                print(line)
            except Exception as exc:  # pragma: no cover - operational tool
                await db.rollback()
                print(f"  company={cid} | FAILED: {exc!r}")

    print("Done.")


async def _resolve_companies(db, company_id: UUID | None) -> list[UUID]:
    if company_id is not None:
        return [company_id]
    res = await db.execute(select(Company.id))
    return [row[0] for row in res.all()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed default CXO mappings")
    parser.add_argument(
        "--company-id",
        type=UUID,
        default=None,
        help="Single tenant UUID. Omit to seed every company.",
    )
    parser.add_argument(
        "--metric",
        dest="metric_codes",
        action="append",
        choices=list(ALL_METRIC_CODES),
        help=(
            "Restrict to specific metric codes. Repeat the flag for multiple "
            "(e.g. --metric PRODUCTIVITY --metric ABSENTEEISM). Omit to seed all."
        ),
    )
    parser.add_argument(
        "--actor-user-id",
        type=int,
        default=0,
        help="user_id stamped into created_by / updated_by + audit logs.",
    )
    args = parser.parse_args()

    asyncio.run(
        run(
            company_id=args.company_id,
            metric_codes=args.metric_codes,
            actor_user_id=args.actor_user_id,
        )
    )


if __name__ == "__main__":
    main()
