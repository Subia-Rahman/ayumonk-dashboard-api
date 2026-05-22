"""Pytest fixtures for the CXO metrics test suite.

Most tests in this folder require a live Postgres test database (pgcrypto +
the existing schema). The fixtures here skip those tests gracefully when
`TEST_DATABASE_URL` is not set, so unit-style tests still run on developer
machines without Docker.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "config_service" / "app" / "scripts" / "migrations"


# ---------------------------------------------------------------------------
# DB-dependent tests get tagged with @pytest.mark.requires_db
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_db: test needs TEST_DATABASE_URL pointing at a live Postgres",
    )


def pytest_collection_modifyitems(config, items):
    if os.getenv("TEST_DATABASE_URL"):
        return
    skip_marker = pytest.mark.skip(
        reason="TEST_DATABASE_URL not set — see tests/README.md"
    )
    for item in items:
        if "requires_db" in item.keywords:
            item.add_marker(skip_marker)


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    engine = create_async_engine(url, future=True, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:
    factory = sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Migration helpers — used by test_alembic_migrations.py
# ---------------------------------------------------------------------------


def read_migration(filename: str) -> str:
    return (MIGRATIONS_DIR / filename).read_text(encoding="utf-8")


@pytest.fixture
def up_sql() -> str:
    return read_migration("cxo_metrics_up.sql")


@pytest.fixture
def engagement_sql() -> str:
    return read_migration("cxo_metrics_engagement.sql")


@pytest.fixture
def down_sql() -> str:
    return read_migration("cxo_metrics_down.sql")
