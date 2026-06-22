"""Unit tests for MarketStream — draw-runner identification and price extraction."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import MagicMock

from src.streaming.market_stream import MarketStream


# ---------------------------------------------------------------------------
# Catalogue helpers
# ---------------------------------------------------------------------------


def _runner(selection_id: int, runner_name: str):
    return type("Runner", (), {"selection_id": selection_id, "runner_name": runner_name})()


def _catalogue(runners: list, event_name: str = "Arsenal v Chelsea"):
    event = type("Event", (), {"name": event_name})()
    return type("Catalogue", (), {
        "runners": runners,
        "event": event,
        "market_start_time": None,
    })()


def _market(catalogue=None):
    return type("Market", (), {"market_catalogue": catalogue})()


# ---------------------------------------------------------------------------
# _find_draw_selection_id
# ---------------------------------------------------------------------------


def test_find_draw_selection_id_found() -> None:
    cat = _catalogue([_runner(111, "Arsenal"), _runner(222, "The Draw"), _runner(333, "Chelsea")])
    assert MarketStream._find_draw_selection_id(cat) == 222


def test_find_draw_selection_id_not_found() -> None:
    cat = _catalogue([_runner(111, "Home"), _runner(333, "Away")])
    assert MarketStream._find_draw_selection_id(cat) is None


def test_find_draw_selection_id_empty_runners() -> None:
    cat = _catalogue([])
    assert MarketStream._find_draw_selection_id(cat) is None


def test_find_draw_selection_id_no_runners_attribute() -> None:
    empty = type("obj", (), {})()
    assert MarketStream._find_draw_selection_id(empty) is None


# ---------------------------------------------------------------------------
# _extract_draw_prices
# ---------------------------------------------------------------------------


def _price_size(price: float):
    return type("PriceSize", (), {"price": price, "size": 100})()


def _ex(back_prices=None, lay_prices=None):
    return type("Ex", (), {
        "available_to_back": [_price_size(p) for p in (back_prices or [])],
        "available_to_lay": [_price_size(p) for p in (lay_prices or [])],
    })()


def _runner_book(selection_id: int, ex=None):
    return type("RunnerBook", (), {"selection_id": selection_id, "ex": ex})()


def _market_book(market_id: str = "1.23456789", total_matched: int = 100_000, runners=None):
    mb = type("MarketBook", (), {
        "market_id": market_id,
        "total_matched": total_matched,
        "runners": runners or [],
    })()
    return mb


def test_extract_draw_prices_both_present() -> None:
    runners = [
        _runner_book(111, _ex(back_prices=[2.0], lay_prices=[2.02])),
        _runner_book(222, _ex(back_prices=[3.2], lay_prices=[3.3])),
    ]
    mb = _market_book(runners=runners)
    lay, back = MarketStream._extract_draw_prices(mb, 222)
    assert lay == Decimal("3.3")
    assert back == Decimal("3.2")


def test_extract_draw_prices_no_ex() -> None:
    mb = _market_book(runners=[_runner_book(222, None)])
    lay, back = MarketStream._extract_draw_prices(mb, 222)
    assert lay is None
    assert back is None


def test_extract_draw_prices_runner_not_found() -> None:
    mb = _market_book(runners=[_runner_book(111, _ex([2.0], [2.02]))])
    lay, back = MarketStream._extract_draw_prices(mb, 999)
    assert lay is None
    assert back is None


# ---------------------------------------------------------------------------
# process_market_book integration
# ---------------------------------------------------------------------------


def test_process_market_book_new_market_writes_tick() -> None:
    """First update for a market should upsert market and insert a tick."""
    mock_repo = MagicMock()
    db_market = MagicMock()
    db_market.id = uuid.uuid4()
    mock_repo.upsert_market.return_value = db_market

    cat = _catalogue([_runner(111, "Arsenal"), _runner(222, "The Draw"), _runner(333, "Chelsea")])
    market = _market(catalogue=cat)

    runners = [
        _runner_book(111, _ex(back_prices=[2.0], lay_prices=[2.02])),
        _runner_book(222, _ex(back_prices=[3.2], lay_prices=[3.3])),
        _runner_book(333, _ex(back_prices=[3.5], lay_prices=[3.55])),
    ]
    mb = _market_book(market_id="1.98765432", total_matched=50_000, runners=runners)

    stream = MarketStream(
        market_filter=MagicMock(),
        repository=mock_repo,
        run_id=uuid.uuid4(),
    )
    stream.process_market_book(market, mb)

    mock_repo.upsert_market.assert_called_once()
    mock_repo.insert_tick.assert_called_once()
    call = mock_repo.insert_tick.call_args
    assert call.kwargs["draw_lay_price"] == Decimal("3.3")
    assert call.kwargs["draw_back_price"] == Decimal("3.2")
    assert call.kwargs["volume_matched"] == 50_000


def test_process_market_book_no_catalogue_skips() -> None:
    """Market with no catalogue yet should not upsert or write a tick."""
    mock_repo = MagicMock()
    market = _market(catalogue=None)
    mb = _market_book(runners=[])

    stream = MarketStream(market_filter=MagicMock(), repository=mock_repo, run_id=uuid.uuid4())
    stream.process_market_book(market, mb)

    mock_repo.upsert_market.assert_not_called()
    mock_repo.insert_tick.assert_not_called()


def test_process_market_book_no_draw_runner_skips() -> None:
    """Market with no draw runner should not write a tick."""
    mock_repo = MagicMock()
    cat = _catalogue([_runner(111, "Arsenal"), _runner(333, "Chelsea")])
    market = _market(catalogue=cat)
    mb = _market_book(runners=[_runner_book(111, _ex([2.0], [2.02]))])

    stream = MarketStream(market_filter=MagicMock(), repository=mock_repo, run_id=uuid.uuid4())
    stream.process_market_book(market, mb)

    mock_repo.upsert_market.assert_not_called()
    mock_repo.insert_tick.assert_not_called()


def test_process_market_book_no_prices_skips_tick() -> None:
    """Draw runner with no exchange data should not write a tick."""
    mock_repo = MagicMock()
    db_market = MagicMock()
    db_market.id = uuid.uuid4()
    mock_repo.upsert_market.return_value = db_market

    cat = _catalogue([_runner(222, "The Draw")])
    market = _market(catalogue=cat)
    mb = _market_book(runners=[_runner_book(222, None)])

    stream = MarketStream(market_filter=MagicMock(), repository=mock_repo, run_id=uuid.uuid4())
    stream.process_market_book(market, mb)

    mock_repo.upsert_market.assert_called_once()
    mock_repo.insert_tick.assert_not_called()
