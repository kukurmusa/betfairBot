"""Unit tests for DbLoader."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.backtest.db_loader import DbLoader
from src.backtest.loader import MarketData, MarketTick


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KICK_OFF = datetime(2026, 6, 14, 15, 0, 0, tzinfo=UTC)


def _make_db_market(
    betfair_id: str = "1.12345",
    event_name: str = "Arsenal v Chelsea",
    kick_off: datetime | None = KICK_OFF,
) -> MagicMock:
    m = MagicMock()
    m.id = uuid.uuid4()
    m.betfair_market_id = betfair_id
    m.event_name = event_name
    m.kick_off = kick_off
    return m


def _make_db_tick(
    lay: float = 3.2,
    back: float = 3.1,
    volume: int = 80_000,
    recorded_at: datetime | None = None,
) -> MagicMock:
    t = MagicMock()
    t.draw_lay_price = lay
    t.draw_back_price = back
    t.volume_matched = volume
    t.recorded_at = recorded_at or datetime(2026, 6, 14, 14, 30, 0, tzinfo=UTC)
    return t


def _make_repo(
    markets: list | None = None,
    ticks: list | None = None,
    market_by_betfair_id: MagicMock | None = None,
) -> MagicMock:
    repo = MagicMock()
    repo.get_markets_for_run.return_value = markets or []
    repo.get_ticks_for_market.return_value = ticks or []
    repo.get_market_by_betfair_id.return_value = market_by_betfair_id
    return repo


# ---------------------------------------------------------------------------
# load_run
# ---------------------------------------------------------------------------


def test_load_run_returns_market_data_for_each_market() -> None:
    """Returns one MarketData per market that has ticks."""
    markets = [_make_db_market("1.1", "Match A"), _make_db_market("1.2", "Match B")]
    ticks = [_make_db_tick(), _make_db_tick()]
    repo = _make_repo(markets=markets, ticks=ticks)

    result = DbLoader(repo).load_run(uuid.uuid4())

    assert len(result) == 2
    assert {m.event_name for m in result} == {"Match A", "Match B"}


def test_load_run_skips_markets_with_no_ticks() -> None:
    """Markets with no ticks are silently skipped."""
    markets = [_make_db_market("1.1"), _make_db_market("1.2")]
    repo = _make_repo(markets=markets, ticks=[])

    result = DbLoader(repo).load_run(uuid.uuid4())

    assert result == []


def test_load_run_returns_empty_when_no_markets() -> None:
    """Returns an empty list when the run has no markets."""
    repo = _make_repo(markets=[])
    result = DbLoader(repo).load_run(uuid.uuid4())
    assert result == []


def test_load_run_partial_skip() -> None:
    """Markets with ticks are returned; those without are skipped."""
    m1 = _make_db_market("1.1", "Has Ticks")
    m2 = _make_db_market("1.2", "No Ticks")

    def ticks_for_market(market_id: uuid.UUID):
        return [_make_db_tick()] if market_id == m1.id else []

    repo = MagicMock()
    repo.get_markets_for_run.return_value = [m1, m2]
    repo.get_ticks_for_market.side_effect = ticks_for_market

    result = DbLoader(repo).load_run(uuid.uuid4())

    assert len(result) == 1
    assert result[0].event_name == "Has Ticks"


# ---------------------------------------------------------------------------
# load_market (by betfair_market_id)
# ---------------------------------------------------------------------------


def test_load_market_returns_market_data_when_found() -> None:
    """Returns MarketData when the market exists in the DB and has ticks."""
    market = _make_db_market("1.99999", "Liverpool v Everton")
    repo = _make_repo(market_by_betfair_id=market, ticks=[_make_db_tick()])

    result = DbLoader(repo).load_market("1.99999")

    assert result is not None
    assert result.market_id == "1.99999"
    assert result.event_name == "Liverpool v Everton"


def test_load_market_returns_none_when_not_in_db() -> None:
    """Returns None when the Betfair market ID is not in the database."""
    repo = _make_repo(market_by_betfair_id=None)
    result = DbLoader(repo).load_market("1.unknown")
    assert result is None


def test_load_market_returns_none_when_no_ticks() -> None:
    """Returns None when the market exists but has no recorded ticks."""
    market = _make_db_market("1.noticks")
    repo = _make_repo(market_by_betfair_id=market, ticks=[])

    result = DbLoader(repo).load_market("1.noticks")

    assert result is None


# ---------------------------------------------------------------------------
# Tick field conversion
# ---------------------------------------------------------------------------


def test_tick_prices_converted_to_decimal() -> None:
    """draw_lay_price and draw_back_price come out as Decimal."""
    market = _make_db_market()
    tick = _make_db_tick(lay=3.25, back=3.15)
    repo = _make_repo(market_by_betfair_id=market, ticks=[tick])

    result = DbLoader(repo).load_market(market.betfair_market_id)

    assert result is not None
    assert isinstance(result.ticks[0].draw_lay_price, Decimal)
    assert result.ticks[0].draw_lay_price == Decimal("3.25")
    assert result.ticks[0].draw_back_price == Decimal("3.15")


def test_tick_volume_preserved() -> None:
    """volume_matched is passed through unchanged."""
    market = _make_db_market()
    tick = _make_db_tick(volume=123_456)
    repo = _make_repo(market_by_betfair_id=market, ticks=[tick])

    result = DbLoader(repo).load_market(market.betfair_market_id)

    assert result is not None
    assert result.ticks[0].volume == 123_456


def test_tick_timestamp_preserved() -> None:
    """recorded_at maps to MarketTick.timestamp."""
    market = _make_db_market()
    ts = datetime(2026, 6, 14, 15, 5, 30, tzinfo=UTC)
    tick = _make_db_tick(recorded_at=ts)
    repo = _make_repo(market_by_betfair_id=market, ticks=[tick])

    result = DbLoader(repo).load_market(market.betfair_market_id)

    assert result is not None
    assert result.ticks[0].timestamp == ts


def test_kick_off_forwarded_from_market() -> None:
    """Market kick_off is forwarded into MarketData."""
    market = _make_db_market(kick_off=KICK_OFF)
    repo = _make_repo(market_by_betfair_id=market, ticks=[_make_db_tick()])

    result = DbLoader(repo).load_market(market.betfair_market_id)

    assert result is not None
    assert result.kick_off == KICK_OFF


def test_kick_off_none_when_market_has_no_kick_off() -> None:
    """None kick_off is preserved."""
    market = _make_db_market(kick_off=None)
    repo = _make_repo(market_by_betfair_id=market, ticks=[_make_db_tick()])

    result = DbLoader(repo).load_market(market.betfair_market_id)

    assert result is not None
    assert result.kick_off is None


def test_ticks_ordered_by_repository() -> None:
    """Tick ordering is delegated to the repository (tested end-to-end in integration)."""
    market = _make_db_market()
    t1 = _make_db_tick(lay=3.0, recorded_at=datetime(2026, 6, 14, 14, 0, tzinfo=UTC))
    t2 = _make_db_tick(lay=3.5, recorded_at=datetime(2026, 6, 14, 14, 1, tzinfo=UTC))
    repo = _make_repo(market_by_betfair_id=market, ticks=[t1, t2])

    result = DbLoader(repo).load_market(market.betfair_market_id)

    assert result is not None
    assert result.ticks[0].draw_lay_price == Decimal("3.0")
    assert result.ticks[1].draw_lay_price == Decimal("3.5")
