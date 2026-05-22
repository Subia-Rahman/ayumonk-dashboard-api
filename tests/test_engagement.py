"""Engagement compute tests — both Python batch wrapper and SQL function.

The Python wrapper test stubs the DB; the SQL function test requires a real
Postgres database (marked @requires_db).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from config_service.app.services.cxo_metrics import compute_engagement_batch


@pytest.mark.asyncio
async def test_batch_returns_one_entry_per_user_id():
    uid1, uid2, uid3 = uuid4(), uuid4(), uuid4()

    rows_result = MagicMock()
    rows_result.all = MagicMock(
        return_value=[
            (uid1, Decimal("76.0")),
            (uid2, Decimal("0.0")),
            # uid3 deliberately missing from the result set
        ]
    )

    db = MagicMock()
    db.execute = AsyncMock(return_value=rows_result)

    result = await compute_engagement_batch(db, [uid1, uid2, uid3])
    assert result[uid1] == Decimal("76.0")
    assert result[uid2] == Decimal("0.0")
    assert result[uid3] is None  # filled in from setdefault


@pytest.mark.asyncio
async def test_batch_empty_input_returns_empty_dict():
    db = MagicMock()
    db.execute = AsyncMock()
    result = await compute_engagement_batch(db, [])
    assert result == {}
    db.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.requires_db
async def test_compute_user_engagement_returns_null_without_mappings(db_session):
    """A user whose company has no Engagement signal mappings -> NULL."""
    from sqlalchemy import text

    cid = (
        await db_session.execute(
            text(
                "INSERT INTO companies (company_name) "
                "VALUES ('Empty Engagement Co') RETURNING id"
            )
        )
    ).scalar()
    uid = (
        await db_session.execute(
            text(
                "INSERT INTO company_users "
                "(id, full_name, email, company_id, is_active, is_deleted) "
                "VALUES (gen_random_uuid(), 'X', 'x@example.com', :cid, TRUE, FALSE) "
                "RETURNING id"
            ),
            {"cid": cid},
        )
    ).scalar()

    val = (
        await db_session.execute(
            text("SELECT compute_user_engagement(:uid)"),
            {"uid": uid},
        )
    ).scalar()
    assert val is None
