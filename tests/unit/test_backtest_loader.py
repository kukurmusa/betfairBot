"""Unit tests for HistoricalLoader."""

from __future__ import annotations

import bz2
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.backtest.loader import HistoricalLoader, MarketData, MarketTick


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KICK_OFF = datetime(2026, 6, 14, 15, 0, 0, tzinfo=UTC)
PUBLISH_TIME = datetime(2026, 6, 14, 14, 30, 0, tzinfo=UTC)


def _make_runner_def(name: str = "The Draw", selection_id: int = 55) -> MagicMock:
    rd = MagicMock()
    rd.name = name
    rd.id = selection_id
    return rd


def _make_market_def(
    event_name: str = "Man City v Arsenal",
    market_time: datetime = KICK_OFF,
    runners: list | None = None,
) -> MagicMock:
    md = MagicMock()
    md.event_name = event_name
    md.market_time = market_time
    md.runners = runners if runners is not None else [_make_runner_def()]
    return md


def _make_ex(lay_price: float = 3.2, back_price: float = 3.1) -> MagicMock:
    lay = MagicMock()
    lay.price = lay_price
    back = MagicMock()
    back.price = back_price
    ex = MagicMock()
    ex.available_to_lay = [lay]
    ex.available_to_back = [back]
    return ex


def _make_runner_book(selection_id: int = 55, lay: float = 3.2, back: float = 3.1) -> MagicMock:
    rb = MagicMock()
    rb.selection_id = selection_id
    rb.ex = _make_ex(lay, back)
    return rb


def _make_market_book(
    market_id: str = "1.12345",
    market_def: MagicMock | None = None,
    runners: list | None = None,
    volume: int = 100_000,
    publish_time: datetime = PUBLISH_TIME,
) -> MagicMock:
    mb = MagicMock()
    mb.market_id = market_id
    mb.market_definition = market_def if market_def is not None else _make_market_def()
    mb.runners = runners if runners is not None else [_make_runner_book()]
    mb.total_matched = volume
    mb.publish_time = publish_time
    return mb


# ---------------------------------------------------------------------------
# _find_draw_selection_id
# ---------------------------------------------------------------------------


def test_find_draw_returns_correct_id() -> None:
    """Should return the selection_id of 'The Draw' runner."""
    md = _make_market_def(runners=[
        _make_runner_def("Home", 10),
        _make_runner_def("The Draw", 55),
        _make_runner_def("Away", 20),
    ])
    assert HistoricalLoader._find_draw_selection_id(md) == 55


def test_find_draw_returns_none_when_absent() -> None:
    """Returns None when no runner is named 'The Draw'."""
    md = _make_market_def(runners=[
        _make_runner_def("Home", 10),
        _make_runner_def("Away", 20),
    ])
    assert HistoricalLoader._find_draw_selection_id(md) is None


def test_find_draw_returns_none_for_empty_runners() -> None:
    """Returns None when the runners list is empty."""
    md = _make_market_def(runners=[])
    assert HistoricalLoader._find_draw_selection_id(md) is None


# ---------------------------------------------------------------------------
# _extract_tick
# ---------------------------------------------------------------------------


def test_extract_tick_returns_correct_prices() -> None:
    """Should extract lay/back price and volume from the matching runner."""
    mb = _make_market_book(runners=[_make_runner_book(selection_id=55, lay=3.2, back=3.1)])
    tick = HistoricalLoader._extract_tick(mb, draw_selection_id=55)
    assert tick is not None
    assert tick.draw_lay_price == Decimal("3.2")
    assert tick.draw_back_price == Decimal("3.1")
    assert tick.volume == 100_000
    assert tick.timestamp == PUBLISH_TIME


def test_extract_tick_returns_none_when_runner_not_found() -> None:
    """Returns None when no runner matches the draw_selection_id."""
    mb = _make_market_book(runners=[_make_runner_book(selection_id=99)])
    assert HistoricalLoader._extract_tick(mb, draw_selection_id=55) is None


def test_extract_tick_returns_none_when_no_lay_prices() -> None:
    """Returns None when available_to_lay is empty."""
    rb = _make_runner_book()
    rb.ex.available_to_lay = []
    mb = _make_market_book(runners=[rb])
    assert HistoricalLoader._extract_tick(mb, draw_selection_id=55) is None


def test_extract_tick_returns_none_when_no_back_prices() -> None:
    """Returns None when available_to_back is empty."""
    rb = _make_runner_book()
    rb.ex.available_to_back = []
    mb = _make_market_book(runners=[rb])
    assert HistoricalLoader._extract_tick(mb, draw_selection_id=55) is None


def test_extract_tick_adds_utc_when_timestamp_naive() -> None:
    """Naive publish_time is treated as UTC."""
    naive_time = datetime(2026, 6, 14, 14, 30, 0)  # no tzinfo
    mb = _make_market_book(publish_time=naive_time)
    tick = HistoricalLoader._extract_tick(mb, draw_selection_id=55)
    assert tick is not None
    assert tick.timestamp.tzinfo is not None


# ---------------------------------------------------------------------------
# load_file
# ---------------------------------------------------------------------------


def test_load_file_returns_none_for_missing_file() -> None:
    """Returns None (with a logged error) for a file that doesn't exist."""
    loader = HistoricalLoader()
    result = loader.load_file(Path("/nonexistent/file.bz2"))
    assert result is None


def test_load_file_returns_market_data_with_ticks(tmp_path: Path) -> None:
    """Should return a populated MarketData for a valid file."""
    dummy_file = tmp_path / "1.12345"
    dummy_file.write_text("line1\nline2\n", encoding="utf-8")

    mb = _make_market_book()

    with patch("src.backtest.loader.StreamListener") as MockListener:
        instance = MockListener.return_value
        instance.snap.return_value = [mb]

        loader = HistoricalLoader()
        result = loader.load_file(dummy_file)

    assert result is not None
    assert result.market_id == "1.12345"
    assert result.event_name == "Man City v Arsenal"
    assert result.kick_off == KICK_OFF
    assert result.draw_selection_id == 55
    assert len(result.ticks) == 2  # two non-empty lines


def test_load_file_returns_none_when_no_draw_runner(tmp_path: Path) -> None:
    """Returns None when the market has no 'The Draw' runner."""
    dummy_file = tmp_path / "1.99999"
    dummy_file.write_text("line1\n", encoding="utf-8")

    md = _make_market_def(runners=[_make_runner_def("Home", 10)])
    mb = _make_market_book(market_def=md)

    with patch("src.backtest.loader.StreamListener") as MockListener:
        instance = MockListener.return_value
        instance.snap.return_value = [mb]

        result = HistoricalLoader().load_file(dummy_file)

    assert result is None


def test_load_file_returns_none_when_no_valid_ticks(tmp_path: Path) -> None:
    """Returns None when every tick is missing prices."""
    dummy_file = tmp_path / "1.00001"
    dummy_file.write_text("line1\n", encoding="utf-8")

    rb = _make_runner_book()
    rb.ex.available_to_lay = []  # no lay prices
    mb = _make_market_book(runners=[rb])

    with patch("src.backtest.loader.StreamListener") as MockListener:
        instance = MockListener.return_value
        instance.snap.return_value = [mb]

        result = HistoricalLoader().load_file(dummy_file)

    assert result is None


def test_load_file_skips_parse_errors_gracefully(tmp_path: Path) -> None:
    """A bad line doesn't abort processing — valid lines still produce ticks."""
    dummy_file = tmp_path / "1.55555"
    dummy_file.write_text("bad_line\ngood_line\n", encoding="utf-8")

    mb = _make_market_book()
    call_count = [0]

    def snap_side_effect():
        return [mb]

    def on_data_side_effect(line: str):
        call_count[0] += 1
        if line == "bad_line":
            raise ValueError("parse error")

    with patch("src.backtest.loader.StreamListener") as MockListener:
        instance = MockListener.return_value
        instance.on_data.side_effect = on_data_side_effect
        instance.snap.side_effect = snap_side_effect

        result = HistoricalLoader().load_file(dummy_file)

    # Only the good line produced a tick
    assert result is not None
    assert len(result.ticks) == 1


# ---------------------------------------------------------------------------
# load_directory
# ---------------------------------------------------------------------------


def test_load_directory_yields_valid_markets(tmp_path: Path) -> None:
    """Yields one MarketData per parseable file, skipping ones without data."""
    for name in ("1.111.bz2", "1.222.bz2"):
        (tmp_path / name).write_bytes(bz2.compress(b"line\n"))

    mb = _make_market_book()

    with patch("src.backtest.loader.StreamListener") as MockListener:
        instance = MockListener.return_value
        instance.snap.return_value = [mb]

        results = list(HistoricalLoader().load_directory(tmp_path))

    assert len(results) == 2
