"""Numerical correctness for the Productivity calculation.

The math in v_user_cxo's WEIGHTED_AVG branch is:

    productivity = LEAST(100, GREATEST(0,
        ((SUM(weight * score) / SUM(weight)) - 1) / 4 * 100
    ))

Tested here by computing the expected value in Python from the methodology
defaults + a synthetic employee's scores, then asserting that v_user_cxo
yields the same number (±0.1).
"""

from decimal import Decimal

import pytest


# Default Productivity weights from the methodology document (six KPIs).
PRODUCTIVITY_DEFAULTS = {
    "Stress":    Decimal("0.300"),
    "Sleep":     Decimal("0.250"),
    "Energy":    Decimal("0.200"),
    "Pain":      Decimal("0.100"),
    "Activity":  Decimal("0.100"),
    "Digestion": Decimal("0.050"),
}


def _expected_productivity(scores: dict[str, int]) -> Decimal:
    """Pure-Python implementation of the SQL formula. Used by the unit test
    and copy-pasteable into a notebook for sanity-checking."""
    weighted_sum = Decimal("0")
    weight_total = Decimal("0")
    for kpi, weight in PRODUCTIVITY_DEFAULTS.items():
        weighted_sum += weight * Decimal(scores[kpi])
        weight_total += weight
    raw = ((weighted_sum / weight_total) - Decimal("1")) / Decimal("4") * Decimal("100")
    raw = max(Decimal("0"), min(Decimal("100"), raw))
    return raw.quantize(Decimal("0.1"))


def test_python_reference_value_for_known_scores():
    """One employee with these scores -> Productivity = 70.0."""
    scores = {
        "Stress": 4,
        "Sleep": 4,
        "Energy": 4,
        "Pain": 3,
        "Activity": 3,
        "Digestion": 3,
    }
    # Manual: weighted avg = 0.3*4 + 0.25*4 + 0.2*4 + 0.1*3 + 0.1*3 + 0.05*3
    #                       = 1.2 + 1.0 + 0.8 + 0.3 + 0.3 + 0.15 = 3.75
    # weight_total = 1.0
    # raw = ((3.75 - 1) / 4) * 100 = 68.75 ~> 68.8 (one-decimal rounding)
    assert _expected_productivity(scores) == Decimal("68.8")


@pytest.mark.asyncio
@pytest.mark.requires_db
async def test_v_user_cxo_matches_reference(db_session):
    """Fixture: one employee with the scores above. v_user_cxo.productivity_pct
    must match the Python reference within 0.1."""
    from sqlalchemy import text

    cid = (
        await db_session.execute(
            text(
                "INSERT INTO companies (company_name) "
                "VALUES ('Math Test Co') RETURNING id"
            )
        )
    ).scalar()
    uid = (
        await db_session.execute(
            text(
                "INSERT INTO company_users "
                "(id, full_name, email, company_id, is_active, is_deleted) "
                "VALUES (gen_random_uuid(), 'M', 'm@example.com', :cid, TRUE, FALSE) "
                "RETURNING id"
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

    # Create the six KPIs + one question per KPI + one answer per question.
    scores = {
        "Stress": 4, "Sleep": 4, "Energy": 4,
        "Pain": 3,   "Activity": 3, "Digestion": 3,
    }
    response_id = "resp-math-1"
    await db_session.execute(
        text(
            "INSERT INTO employee_form_response "
            "(id, company_id, form_id, employee_email, response_id, submitted_at, is_latest) "
            "VALUES (gen_random_uuid(), :cid::text, 'f1', 'm@example.com', :rid, now(), TRUE)"
        ),
        {"cid": cid, "rid": response_id},
    )
    for name, score in scores.items():
        kpi_key = (
            await db_session.execute(
                text(
                    "INSERT INTO kpis (kpi_key, company_id, display_name) "
                    "VALUES (gen_random_uuid(), :cid, :n) RETURNING kpi_key"
                ),
                {"cid": cid, "n": name},
            )
        ).scalar()
        await db_session.execute(
            text(
                "INSERT INTO kpi_questions "
                "(id, company_id, kpi, question_code, question_text) "
                "VALUES (gen_random_uuid(), :cid, :kk, :qc, 'q')"
            ),
            {"cid": cid, "kk": kpi_key, "qc": f"Q_{name.upper()}"},
        )
        await db_session.execute(
            text(
                "INSERT INTO employee_form_answer "
                "(id, response_id, question_code, score) "
                "VALUES (gen_random_uuid(), :rid, :qc, :s)"
            ),
            {"rid": response_id, "qc": f"Q_{name.upper()}", "s": score},
        )
        # Mapping
        await db_session.execute(
            text(
                "INSERT INTO cxo_metric_kpi_mapping "
                "(company_id, metric_id, kpi_key, weight) "
                "VALUES (:cid, :mid, :kk, :w)"
            ),
            {
                "cid": cid,
                "mid": metric_id,
                "kk": kpi_key,
                "w": PRODUCTIVITY_DEFAULTS[name],
            },
        )
    await db_session.flush()

    got = (
        await db_session.execute(
            text(
                "SELECT productivity_pct FROM v_user_cxo WHERE user_id = :uid"
            ),
            {"uid": uid},
        )
    ).scalar()
    assert got is not None
    assert abs(Decimal(str(got)) - _expected_productivity(scores)) <= Decimal("0.1")
