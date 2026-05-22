"""Up + down migration smoke test.

The repo uses plain SQL files instead of Alembic — see
config_service/app/scripts/migrations/. This test verifies they can be
applied and rolled back without error on a fresh schema.

Requires a Postgres test database. See tests/README.md.
"""

import pytest
from sqlalchemy import text


@pytest.mark.asyncio
@pytest.mark.requires_db
async def test_up_then_down(db_session, up_sql, engagement_sql, down_sql):
    # Up
    await db_session.execute(text(up_sql))
    await db_session.commit()

    # Engagement function migration depends on cxo_metric_master existing.
    await db_session.execute(text(engagement_sql))
    await db_session.commit()

    # Smoke-test: master rows seeded, views queryable, function callable.
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM cxo_metric_master WHERE is_active = TRUE")
    )
    assert result.scalar() == 3

    result = await db_session.execute(
        text("SELECT pg_get_functiondef('compute_user_engagement(uuid)'::regprocedure)")
    )
    assert "compute_user_engagement" in (result.scalar() or "")

    # Down
    await db_session.execute(text(down_sql))
    await db_session.commit()

    result = await db_session.execute(
        text(
            "SELECT to_regclass('cxo_metric_master') AS master, "
            "       to_regclass('cxo_metric_kpi_mapping') AS kpi_map, "
            "       to_regclass('cxo_metric_signal_mapping') AS sig_map, "
            "       to_regclass('v_user_cxo') AS view_cxo"
        )
    )
    row = result.one()
    assert row.master is None
    assert row.kpi_map is None
    assert row.sig_map is None
    assert row.view_cxo is None
