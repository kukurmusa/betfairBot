"""Unit tests for BacktestReplay."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest

from src.backtest.loader import MarketData, MarketTick
from src.backtest.replay import BacktestReplay, ReplayResult
from src.config.settings import StrategyConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KICK_OFF = datetime(2026, 6, 14, 15, 0, 0, tzinfo=UTC)


def _make_tick(
    lay: str = "3.20",
    back: str = "3.10",
    ts: datetime | None = None,
) -> MarketTick:
    return MarketTick(
        timestamp=ts or datetime(2026, 6, 14, 14, 30, 0, tzinfo=UTC),
        draw_lay_price=Decimal(lay),
        draw_back_price=Decimal(back),
        volume=80_000,
    )


def _make_market(market_id: str = "1.12345", n_ticks: int = 3) -> MarketData:
    return MarketData(
        market_id=market_id,
        event_name=f"Market {market_id}",
        kick_off=KICK_OFF,
        draw_selection_id=55,
        ticks=[_make_tick() for _ in range(n_ticks)],
    )


def _make_repo(run_id: uuid.UUID | None = None) -> MagicMock:
    repo = MagicMock()
    run = MagicMock()
    run.id = run_id or uuid.uuid4()
    repo.create_run.return_value = run
    repo.upsert_market.return_value = MagicMock(id=uuid.uuid4())
    return repo


def _mock_risk_manager(pnl: Decimal = Decimal("0")) -> MagicMock:
    rm = MagicMock()
    rm.daily_pnl = pnl
    return rm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_creates_backtest_run() -> None:
    """run() must create a DB run with mode='backtest'."""
    repo = _make_repo()

    with patch("src.backtest.replay.RiskManager", return_value=_mock_risk_manager()), \
         patch("src.backtest.replay.GoalDetector"), \
         patch("src.backtest.replay.LTDStrategy"):
        BacktestReplay(StrategyConfig(), repo).run([])

    repo.create_run.assert_called_once_with(mode="backtest", strategy_name="ltd_v1")


def test_run_upserts_market_for_each_input() -> None:
    """run() must call upsert_market once per MarketData."""
    repo = _make_repo()
    markets = [_make_market("1.1"), _make_market("1.2")]

    with patch("src.backtest.replay.RiskManager", return_value=_mock_risk_manager()), \
         patch("src.backtest.replay.GoalDetector"), \
         patch("src.backtest.replay.LTDStrategy"):
        BacktestReplay(StrategyConfig(), repo).run(markets)

    assert repo.upsert_market.call_count == 2
    called_ids = [c.kwargs["betfair_market_id"] for c in repo.upsert_market.call_args_list]
    assert "1.1" in called_ids
    assert "1.2" in called_ids


def test_run_feeds_ticks_to_strategy() -> None:
    """run() must call strategy.on_market_book for every tick in every market."""
    repo = _make_repo()
    markets = [_make_market("1.1", n_ticks=4), _make_market("1.2", n_ticks=2)]

    mock_strategy_instance = MagicMock()
    with patch("src.backtest.replay.RiskManager", return_value=_mock_risk_manager()), \
         patch("src.backtest.replay.GoalDetector"), \
         patch("src.backtest.replay.LTDStrategy", return_value=mock_strategy_instance):
        BacktestReplay(StrategyConfig(), repo).run(markets)

    assert mock_strategy_instance.on_market_book.call_count == 6  # 4 + 2


def test_run_ends_run_with_pnl() -> None:
    """run() must call end_run with the risk manager's daily_pnl."""
    repo = _make_repo()
    run_id = repo.create_run.return_value.id

    with patch("src.backtest.replay.RiskManager", return_value=_mock_risk_manager(Decimal("12.50"))), \
         patch("src.backtest.replay.GoalDetector"), \
         patch("src.backtest.replay.LTDStrategy"):
        BacktestReplay(StrategyConfig(), repo).run([])

    repo.end_run.assert_called_once_with(run_id, total_pnl=Decimal("12.50"))


def test_run_returns_correct_replay_result() -> None:
    """ReplayResult should report the exact market and tick counts."""
    repo = _make_repo()
    markets = [_make_market("1.1", n_ticks=5), _make_market("1.2", n_ticks=3)]

    with patch("src.backtest.replay.RiskManager", return_value=_mock_risk_manager()), \
         patch("src.backtest.replay.GoalDetector"), \
         patch("src.backtest.replay.LTDStrategy"):
        result = BacktestReplay(StrategyConfig(), repo).run(markets)

    assert isinstance(result, ReplayResult)
    assert result.markets_processed == 2
    assert result.ticks_processed == 8


def test_run_with_empty_market_list_still_creates_run() -> None:
    """An empty market list should create and end the run with zero ticks."""
    repo = _make_repo()

    with patch("src.backtest.replay.RiskManager", return_value=_mock_risk_manager()), \
         patch("src.backtest.replay.GoalDetector"), \
         patch("src.backtest.replay.LTDStrategy"):
        result = BacktestReplay(StrategyConfig(), repo).run([])

    repo.create_run.assert_called_once()
    repo.end_run.assert_called_once()
    assert result.markets_processed == 0
    assert result.ticks_processed == 0


def test_on_market_book_called_with_correct_kick_off() -> None:
    """kick_off from MarketData must be forwarded to on_market_book."""
    repo = _make_repo()
    market = _make_market("1.99", n_ticks=1)

    mock_strategy = MagicMock()
    with patch("src.backtest.replay.RiskManager", return_value=_mock_risk_manager()), \
         patch("src.backtest.replay.GoalDetector"), \
         patch("src.backtest.replay.LTDStrategy", return_value=mock_strategy):
        BacktestReplay(StrategyConfig(), repo).run([market])

    kwargs = mock_strategy.on_market_book.call_args.kwargs
    assert kwargs["kick_off"] == KICK_OFF
    assert kwargs["market_id"] == "1.99"
