"""Unit tests for MarketStream — draw identification and market book parsing."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.streaming.market_stream import MarketStream, _StreamContext


# ---------------------------------------------------------------------------
# _find_draw_selection_id
# ---------------------------------------------------------------------------


class _FakeRunner:
    """Mock for a betfairlightweight runner with description."""

    def __init__(self, selection_id: int, runner_name: str) -> None:
        self.selection_id = selection_id
        self.description = type("obj", (), {"runner_name": runner_name})()


class _FakeMarketDefinition:
    """Mock for betfairlightweight MarketDefinition."""

    def __init__(
        self,
        runners: list[_FakeRunner],
        event_name: str = "Arsenal v Chelsea",
        market_time: str | None = "2026-06-15T15:00:00Z",
    ) -> None:
        self.runners = runners
        self.event_name = event_name
        self.market_time = market_time
        self.home_team = "Arsenal"
        self.away_team = "Chelsea"


def test_find_draw_selection_id_found() -> None:
    """Should return the selection_id of 'The Draw' runner."""
    runners = [
        _FakeRunner(111, "Arsenal"),
        _FakeRunner(222, "The Draw"),
        _FakeRunner(333, "Chelsea"),
    ]
    market_def = _FakeMarketDefinition(runners)

    result = MarketStream._find_draw_selection_id(market_def)
    assert result == 222


def test_find_draw_selection_id_not_found() -> None:
    """Should return None when no draw runner exists."""
    runners = [
        _FakeRunner(111, "Home"),
        _FakeRunner(333, "Away"),
    ]
    market_def = _FakeMarketDefinition(runners)

    result = MarketStream._find_draw_selection_id(market_def)
    assert result is None


def test_find_draw_selection_id_empty_runners() -> None:
    """Should return None for empty runner list."""
    market_def = _FakeMarketDefinition([])

    result = MarketStream._find_draw_selection_id(market_def)
    assert result is None


def test_find_draw_selection_id_no_runners_attribute() -> None:
    """Should handle MarketDef without a runners attribute."""
    market_def = type("obj", (), {})()
    result = MarketStream._find_draw_selection_id(market_def)
    assert result is None


# ---------------------------------------------------------------------------
# _handle_market_book (via a mock-heavy test)
# ---------------------------------------------------------------------------

class _FakeExOffers:
    """Mock for betfairlightweight exchange prices."""

    def __init__(self, available_to_back: list | None = None, available_to_lay: list | None = None) -> None:
        self.available_to_back = available_to_back or []
        self.available_to_lay = available_to_lay or []


class _FakePriceSize:
    def __init__(self, price: float, size: float) -> None:
        self.price = price
        self.size = size


class _FakeMarketBookRunner:
    def __init__(self, selection_id: int, ex: _FakeExOffers | None = None) -> None:
        self.selection_id = selection_id
        self.ex = ex


class _FakeMarketBook:
    """Mock for betfairlightweight MarketBook."""

    def __init__(
        self,
        market_id: str = "1.23456789",
        total_matched: int = 125_000,
        runners: list[_FakeMarketBookRunner] | None = None,
        market_definition: _FakeMarketDefinition | None = None,
    ) -> None:
        self.id = market_id
        self.total_matched = total_matched
        self.runners = runners or []
        self.market_definition = market_definition


@pytest.mark.asyncio
async def test_handle_market_book_new_market() -> None:
    """First market book should upsert a market and insert a tick."""
    mock_repo = AsyncMock()
    mock_repo.get_market_by_betfair_id.return_value = None

    db_market = MagicMock()
    db_market.id = uuid.uuid4()
    mock_repo.upsert_market.return_value = db_market

    draw_runners = [
        _FakeRunner(111, "Arsenal"),
        _FakeRunner(222, "The Draw"),
        _FakeRunner(333, "Chelsea"),
    ]
    market_def = _FakeMarketDefinition(draw_runners)

    book_runners = [
        _FakeMarketBookRunner(111, _FakeExOffers(
            [_FakePriceSize(2.0, 100)],
            [_FakePriceSize(2.02, 80)],
        )),
        _FakeMarketBookRunner(333, _FakeExOffers(
            [_FakePriceSize(3.5, 50)],
            [_FakePriceSize(3.55, 40)],
        )),
        _FakeMarketBookRunner(222, _FakeExOffers(
            [_FakePriceSize(3.2, 30)],
            [_FakePriceSize(3.3, 25)],
        )),
    ]
    market_book = _FakeMarketBook(
        market_id="1.98765432",
        total_matched=50_000,
        runners=book_runners,
        market_definition=market_def,
    )

    stream = MarketStream(
        trading_client=MagicMock(),
        competition_ids={"Premier League": "10932509"},
        config=MagicMock(),
        secrets=MagicMock(),
        repository=mock_repo,
        run_id=uuid.uuid4(),
    )

    await stream._handle_market_book(market_book)

    # Should have called upsert_market once
    mock_repo.upsert_market.assert_called_once()
    # Should have inserted one tick
    mock_repo.insert_tick.assert_called_once()

    call_args = mock_repo.insert_tick.call_args
    assert call_args.kwargs["draw_lay_price"] == Decimal("3.3")
    assert call_args.kwargs["draw_back_price"] == Decimal("3.2")
    assert call_args.kwargs["volume_matched"] == 50_000


@pytest.mark.asyncio
async def test_handle_market_book_no_prices() -> None:
    """Market book with no exchange offers should not insert a tick."""
    mock_repo = AsyncMock()
    mock_repo.get_market_by_betfair_id.return_value = None

    db_market = MagicMock()
    db_market.id = uuid.uuid4()
    mock_repo.upsert_market.return_value = db_market

    draw_runners = [
        _FakeRunner(111, "Arsenal"),
        _FakeRunner(222, "The Draw"),
        _FakeRunner(333, "Chelsea"),
    ]
    market_def = _FakeMarketDefinition(draw_runners)

    # Draw runner has no exchange data
    book_runners = [
        _FakeMarketBookRunner(222, None),  # No ex
    ]
    market_book = _FakeMarketBook(
        runners=book_runners,
        market_definition=market_def,
    )

    stream = MarketStream(
        trading_client=MagicMock(),
        competition_ids={},
        config=MagicMock(),
        secrets=MagicMock(),
        repository=mock_repo,
        run_id=uuid.uuid4(),
    )

    await stream._handle_market_book(market_book)

    # Market should be upserted but no tick inserted (no prices)
    mock_repo.upsert_market.assert_called_once()
    mock_repo.insert_tick.assert_not_called()
