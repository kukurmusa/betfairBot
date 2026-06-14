"""Shared test fixtures.

Provides a clean database session per test (integration tests) and
sample market data (unit tests).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base
from src.db.repository import Repository

# Use a test database URL — default to local Postgres, override via env
TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL_TEST",
    "postgresql+asyncpg://bot:bot_password@localhost:5432/betfair_ltd_test",
)


@pytest_asyncio.fixture(name="db_session")
async def db_session_fixture() -> AsyncGenerator[AsyncSession, None]:
    """Create a clean test database with all tables, drop after the test.

    Each test gets its own session — no test data leaks between tests.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    # Create schema and tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    # Tear down
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(name="repository")
async def repository_fixture(db_session: AsyncSession) -> Repository:
    """Return a Repository backed by the test database session."""
    return Repository(db_session)


# ---------------------------------------------------------------------------
# Sample data for unit tests (no DB needed)
# ---------------------------------------------------------------------------


def make_market_definition(
    event_name: str = "Arsenal v Chelsea",
    competition_name: str = "Premier League",
    runners: list[dict] | None = None,
    market_time: str | None = "2026-06-15T15:00:00Z",
) -> dict:
    """Build a dict resembling a betfairlightweight MarketDefinition."""
    if runners is None:
        runners = [
            {"selection_id": 12345, "runner_name": "Arsenal"},
            {"selection_id": 12346, "runner_name": "Chelsea"},
            {"selection_id": 12347, "runner_name": "The Draw"},
        ]
    return {
        "event_name": event_name,
        "competition_name": competition_name,
        "runners": [
            {
                "selection_id": r["selection_id"],
                "description": {"runner_name": r["runner_name"]},
            }
            for r in runners
        ],
        "market_time": market_time,
    }


def make_market_book(
    market_id: str = "1.23456789",
    total_matched: int = 125000,
    draw_selection_id: int = 12347,
    draw_lay_price: float = 3.30,
    draw_back_price: float = 3.20,
) -> dict:
    """Build a dict resembling a betfairlightweight MarketBook with EX_BEST_OFFERS."""
    return {
        "id": market_id,
        "total_matched": total_matched,
        "market_definition": make_market_definition(),
        "runners": [
            {
                "selection_id": 12345,
                "ex": {
                    "available_to_back": [{"price": 2.00, "size": 100}],
                    "available_to_lay": [{"price": 2.02, "size": 80}],
                },
            },
            {
                "selection_id": 12346,
                "ex": {
                    "available_to_back": [{"price": 3.50, "size": 50}],
                    "available_to_lay": [{"price": 3.55, "size": 40}],
                },
            },
            {
                "selection_id": draw_selection_id,
                "ex": {
                    "available_to_back": [{"price": draw_back_price, "size": 30}],
                    "available_to_lay": [{"price": draw_lay_price, "size": 25}],
                },
            },
        ],
    }


# Pre-made sample objects
SAMPLE_CONFIG_YAML = """
strategy:
  max_entry_odds: 3.5
  stake: 10.0
  commission_rate: 0.05
  goal_spike_threshold: 0.30
  stop_loss_minute: 60
  min_market_volume: 50000
  daily_loss_limit: 50.0
streaming:
  target_competitions:
    - "Premier League"
    - "Championship"
  max_reconnect_attempts: 5
  reconnect_base_delay_s: 1.0
logging:
  level: INFO
"""

SAMPLE_SECRETS_ENV = {
    "BETFAIR_APP_KEY": "test-app-key-123",
    "BETFAIR_USERNAME": "test_user",
    "BETFAIR_CERT_PATH": __file__,  # exists because this file exists
    "BETFAIR_CERT_KEY_PATH": __file__,  # same
}
