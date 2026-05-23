"""Default seeder tests.

The 'happy path' case requires a live DB (KPIs exist for the test company,
the cxo_metric_master rows are seeded). The 'missing KPI' case can be
tested with a stubbed db that returns an empty kpi_name->kpi_key map.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from config_service.app.schemas.cxo_metrics import SeedResult
from config_service.app.services import cxo_seeder
from config_service.app.services.cxo_seeder import (
    ALL_METRIC_CODES,
    seed_default_cxo_mappings,
)


@pytest.mark.asyncio
@pytest.mark.requires_db
async def test_full_seed_happy_path(db_session):
    """6 productivity rows, 5 absenteeism rows, 4 engagement signals."""
    from sqlalchemy import text

    # Caller is expected to have already created a company with all the
    # named KPIs. Tests in CI seed those in a shared fixture; here we assert
    # the contract by reading after the seed.
    company_id = await _ensure_test_company(db_session)
    actor = 9999

    result = await seed_default_cxo_mappings(
        db_session, company_id=company_id, actor_user_id=actor
    )
    await db_session.commit()

    assert set(result.seeded) == set(ALL_METRIC_CODES)
    assert result.errors == []

    counts = (
        await db_session.execute(
            text(
                """
                SELECT m.metric_code, COUNT(map.id)
                FROM cxo_metric_master m
                LEFT JOIN cxo_metric_kpi_mapping map
                    ON map.metric_id = m.id
                   AND map.company_id = :cid
                   AND map.is_active
                GROUP BY m.metric_code
                """
            ),
            {"cid": company_id},
        )
    ).all()
    code_to_count = dict(counts)
    assert code_to_count.get("PRODUCTIVITY") == 6
    assert code_to_count.get("ABSENTEEISM") == 5

    signal_count = (
        await db_session.execute(
            text(
                """
                SELECT COUNT(*) FROM cxo_metric_signal_mapping
                WHERE company_id = :cid AND is_active
                """
            ),
            {"cid": company_id},
        )
    ).scalar()
    assert signal_count == 4


async def _ensure_test_company(db_session):
    """Create a company with the six methodology KPIs if it doesn't exist
    already. Returns its id."""
    from sqlalchemy import text

    cid_row = await db_session.execute(
        text(
            "INSERT INTO companies (company_name) "
            "VALUES ('Seeder Test Co') RETURNING id"
        )
    )
    cid = cid_row.scalar()
    for name in ["Stress", "Sleep", "Energy", "Pain", "Activity", "Digestion"]:
        await db_session.execute(
            text(
                "INSERT INTO kpis (kpi_key, company_id, display_name) "
                "VALUES (gen_random_uuid(), :cid, :n)"
            ),
            {"cid": cid, "n": name},
        )
    await db_session.flush()
    return cid


# ---------------------------------------------------------------------------
# Missing-KPI case — stubbed DB so we don't need live KPIs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_kpi_is_logged_and_listed_in_skipped():
    """When a required KPI is missing, the seeder logs and continues."""
    company_id = uuid4()
    actor = 42

    # Stub: no KPIs found => every default lookup falls into skipped_kpis.
    async def fake_resolve(*args, **kwargs):
        return {}  # empty kpi_name_to_key

    fake_master_row = MagicMock()
    fake_master_row.id = uuid4()
    fake_master_row.metric_code = "PRODUCTIVITY"
    fake_master_row.formula_type = "WEIGHTED_AVG"

    async def fake_load_masters(_db):
        # Return only PRODUCTIVITY so we hit the kpi-mapping branch.
        return [fake_master_row]

    db = MagicMock()
    db.info = {}

    class _FakeNested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    db.begin_nested = lambda: _FakeNested()
    db.execute = AsyncMock()
    db.flush = AsyncMock()

    audit_patch = patch(
        "config_service.app.services.cxo_seeder.AuditLogService"
    )
    with (
        patch.object(cxo_seeder, "_resolve_company_kpis", fake_resolve),
        patch.object(cxo_seeder, "_load_metric_masters", fake_load_masters),
        audit_patch as mock_audit_cls,
    ):
        mock_audit = MagicMock()
        mock_audit.log = AsyncMock()
        mock_audit.queue = MagicMock()  # queue() is sync (just adds to session)
        mock_audit_cls.return_value = mock_audit

        result = await seed_default_cxo_mappings(
            db,
            company_id=company_id,
            actor_user_id=actor,
            metric_codes=["PRODUCTIVITY"],
        )

    assert "PRODUCTIVITY" in result.seeded
    # Every PRODUCTIVITY default KPI should land in skipped_kpis.
    assert set(result.skipped_kpis) == {
        "Stress", "Sleep", "Energy", "Pain", "Activity", "Digestion"
    }
    assert result.errors == []
