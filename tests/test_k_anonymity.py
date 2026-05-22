"""K-anonymity bucket suppression test.

Verifies that buckets with cohort_size < companies.k_anonymity_floor are
dropped from the response and counted in meta.suppressedBuckets.

This is implemented purely in the service layer (CxoByDimensionService),
so we can test it by stubbing the SQL execute() call rather than spinning
up a real DB.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from config_service.app.services.cxo_dashboard import CxoByDimensionService


@pytest.mark.asyncio
async def test_buckets_below_floor_are_suppressed():
    """Floor=5: a bucket with cohort_size=3 must be dropped and counted as
    suppressed, while a bucket with cohort_size=10 stays."""

    # First call resolves the k-anonymity floor; second call is the cohort
    # query whose rows we feed in directly.
    floor_result = MagicMock()
    floor_result.scalar = MagicMock(return_value=5)

    rows_result = MagicMock()
    rows_result.all = MagicMock(
        return_value=[
            ("Engineering", 76.9, 10),  # kept
            ("Marketing",    72.0,  3),  # suppressed (< 5)
            ("Sales",        80.0,  8),  # kept
        ]
    )

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[floor_result, rows_result])

    svc = CxoByDimensionService(db)
    result = await svc.fetch(
        metric="productivity",
        breakdown="dept",
        company_id="00000000-0000-0000-0000-000000000001",
        department_id=None,
        age_band=None,
        gender=None,
    )

    labels = [b["label"] for b in result["data"]]
    assert "Marketing" not in labels
    assert "Engineering" in labels
    assert "Sales" in labels
    assert result["meta"]["suppressedBuckets"] == 1
    assert result["meta"]["cohortSize"] == 21
    assert result["meta"]["kAnonymityFloor"] == 5


@pytest.mark.asyncio
async def test_age_band_ordering_is_canonical():
    floor_result = MagicMock()
    floor_result.scalar = MagicMock(return_value=1)

    rows_result = MagicMock()
    rows_result.all = MagicMock(
        return_value=[
            ("50+",    70.0, 10),
            ("20-25",  80.0, 10),
            ("31-35",  75.0, 10),
            ("zz-foo", 60.0, 10),   # outside canonical set
            ("26-30",  78.0, 10),
        ]
    )

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[floor_result, rows_result])

    svc = CxoByDimensionService(db)
    result = await svc.fetch(
        metric="productivity",
        breakdown="age_band",
        company_id="00000000-0000-0000-0000-000000000001",
        department_id=None,
        age_band=None,
        gender=None,
    )
    labels = [b["label"] for b in result["data"]]
    assert labels == ["20-25", "26-30", "31-35", "50+", "zz-foo"]
