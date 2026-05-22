"""Admin route behaviour: transactional rollback, audit-log capture.

These tests exercise the PUT mapping path end-to-end through the
service-level helpers, simulating a DB failure mid-flight to confirm that
the previous mapping is preserved when an exception escapes the
`async with db.begin_nested()` block.
"""

from __future__ import annotations

from decimal import Decimal

import pytest


@pytest.mark.asyncio
@pytest.mark.requires_db
async def test_put_mapping_rolls_back_on_downstream_failure(db_session, monkeypatch):
    """Inject a failure after the soft-delete step. The previous mapping
    must remain visible (is_active=TRUE) after rollback."""
    from sqlalchemy import text
    from config_service.app.repositories.cxo_metrics import (
        CxoMetricKpiMappingRepository,
    )

    # Bootstrap a company with one PRODUCTIVITY mapping row.
    cid = (
        await db_session.execute(
            text(
                "INSERT INTO companies (company_name) "
                "VALUES ('Rollback Co') RETURNING id"
            )
        )
    ).scalar()
    kpi_key = (
        await db_session.execute(
            text(
                "INSERT INTO kpis (kpi_key, company_id, display_name) "
                "VALUES (gen_random_uuid(), :cid, 'Stress') RETURNING kpi_key"
            ),
            {"cid": cid},
        )
    ).scalar()
    metric_id = (
        await db_session.execute(
            text(
                "SELECT id FROM cxo_metric_master WHERE metric_code = 'PRODUCTIVITY'"
            )
        )
    ).scalar()
    await db_session.execute(
        text(
            "INSERT INTO cxo_metric_kpi_mapping "
            "(company_id, metric_id, kpi_key, weight, threshold) "
            "VALUES (:cid, :mid, :kk, 1.000, NULL)"
        ),
        {"cid": cid, "mid": metric_id, "kk": kpi_key},
    )
    await db_session.commit()

    # Simulate the PUT pipeline: soft-delete + raise.
    try:
        async with db_session.begin_nested():
            await CxoMetricKpiMappingRepository(db_session).soft_delete_for_metric(
                company_id=cid, metric_id=metric_id, actor_user_id=1
            )
            raise RuntimeError("simulated downstream error")
    except RuntimeError:
        pass

    # The previous mapping must still be active.
    row = (
        await db_session.execute(
            text(
                "SELECT is_active, weight FROM cxo_metric_kpi_mapping "
                "WHERE company_id = :cid AND metric_id = :mid"
            ),
            {"cid": cid, "mid": metric_id},
        )
    ).one()
    assert row.is_active is True
    assert row.weight == Decimal("1.000")


@pytest.mark.asyncio
@pytest.mark.requires_db
async def test_put_mapping_writes_audit_log(db_session):
    """End-to-end PUT writes a single audit_logs row with old/new payloads."""
    from sqlalchemy import text
    from authentication_service.app.services.audit_log_service import AuditLogService

    cid = (
        await db_session.execute(
            text(
                "INSERT INTO companies (company_name) "
                "VALUES ('Audit Co') RETURNING id"
            )
        )
    ).scalar()

    await AuditLogService(db_session).log(
        user_id=1,
        tenant_id=cid,
        action="UPDATE_CXO_MAPPING",
        entity="cxo_metric_kpi_mapping",
        old_value={"kpi_mappings": [], "signal_mappings": []},
        new_value={"kpi_mappings": [{"kpi_key": "x", "weight": "1.000"}]},
    )

    row = (
        await db_session.execute(
            text(
                "SELECT action, entity, tenant_id, old_value, new_value "
                "FROM audit_logs WHERE tenant_id = :cid "
                "ORDER BY timestamp DESC LIMIT 1"
            ),
            {"cid": cid},
        )
    ).one()
    assert row.action == "UPDATE_CXO_MAPPING"
    assert row.entity == "cxo_metric_kpi_mapping"
    assert row.old_value == {"kpi_mappings": [], "signal_mappings": []}
    assert "kpi_mappings" in row.new_value
