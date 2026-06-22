"""Shared test fixtures."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import Base
from src.db.repository import Repository

TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL_TEST",
    "postgresql+psycopg2://bot:bot_password@localhost:5432/betfair_ltd_test",
)


@pytest.fixture(name="db_session")
def db_session_fixture() -> Generator[Session, None, None]:
    """Create a clean test database with all tables, drop after the test."""
    engine = create_engine(TEST_DATABASE_URL, echo=False)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(name="repository")
def repository_fixture(db_session: Session) -> Repository:
    """Return a Repository backed by the test database session."""
    return Repository(db_session)


# ---------------------------------------------------------------------------
# Helpers for unit tests (no DB needed)
# ---------------------------------------------------------------------------


def make_catalogue_runner(selection_id: int, runner_name: str):
    """Build a mock flumine RunnerCatalogue object."""
    return type("RunnerCatalogue", (), {"selection_id": selection_id, "runner_name": runner_name})()


def make_catalogue(
    event_name: str = "Arsenal v Chelsea",
    runners: list | None = None,
    market_start_time: datetime | None = None,
):
    """Build a mock flumine MarketCatalogue object."""
    if runners is None:
        runners = [
            make_catalogue_runner(12345, "Arsenal"),
            make_catalogue_runner(12346, "Chelsea"),
            make_catalogue_runner(12347, "The Draw"),
        ]
    event = type("Event", (), {"name": event_name})()
    return type("MarketCatalogue", (), {
        "runners": runners,
        "event": event,
        "market_start_time": market_start_time,
    })()


SAMPLE_CONFIG_YAML = """
paper_mode: true
strategy:
  max_entry_odds: 3.5
  stake: 10.0
  commission_rate: 0.05
  goal_spike_threshold: 0.30
  stop_loss_minute: 60
  min_market_volume: 50000
  daily_loss_limit: 50.0
  max_open_positions: 3
  max_liability_per_bet: 5.0
streaming:
  target_competitions:
    - "Premier League"
    - "Championship"
logging:
  level: INFO
"""

SAMPLE_SECRETS_ENV = {
    "BETFAIR_APP_KEY": "test-app-key-123",
    "BETFAIR_USERNAME": "test_user",
    "BETFAIR_CERT_PATH": __file__,
    "BETFAIR_CERT_KEY_PATH": __file__,
}
