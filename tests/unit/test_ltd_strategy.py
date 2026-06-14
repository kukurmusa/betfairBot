"""Unit tests for LTDStrategy — state machine, entry/exit logic.

All external dependencies (Repository, RiskManager, GoalDetector) are
mocked so the strategy logic is tested in isolation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import StrategyConfig
from src.goal_detection.detector import GoalDetectionResult
from src.strategy.ltd_strategy import LTDStrategy, PositionState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 14, 15, 2, 0, tzinfo=UTC)
KICK_OFF = datetime(2026, 6, 14, 15, 0, 0, tzinfo=UTC)
RUN_ID = uuid.uuid4()
DB_MARKET_ID = uuid.uuid4()


def _make_config(**overrides: float | int) -> StrategyConfig:
    """Build a StrategyConfig with defaults, overridden as needed."""
    defaults: dict[str, float | int] = {
        "max_entry_odds": 3.5,
        "stake": 10.0,
        "commission_rate": 0.05,
        "goal_spike_threshold": 0.30,
        "stop_loss_minute": 60,
        "min_market_volume": 50_000,
        "daily_loss_limit": 50.0,
    }
    defaults.update(overrides)
    return StrategyConfig(**defaults)  # type: ignore[arg-type]


def _make_risk_manager(**overrides) -> MagicMock:
    """Create a RiskManager mock with sensible defaults for all methods."""
    rm = MagicMock()
    rm.check_kill_switch.return_value = False
    rm.daily_pnl = Decimal("0.00")
    rm.calculate_liability.return_value = Decimal("25.00")
    rm.calculate_green_up_stake.return_value = Decimal("3.50")
    rm.calculate_commission.return_value = Decimal("0.25")
    rm.update_pnl = AsyncMock()
    for key, value in overrides.items():
        setattr(rm, key, value)
    return rm


def _make_strategy(
    config: StrategyConfig | None = None,
    risk_manager: MagicMock | None = None,
    goal_detector: MagicMock | None = None,
    repository: AsyncMock | None = None,
) -> LTDStrategy:
    """Create a LTDStrategy with mock dependencies.

    Callers who supply their own mocks are responsible for configuring
    return values — _make_strategy only sets defaults for mocks it
    creates itself.
    """
    cfg = config or _make_config()
    rm = risk_manager or _make_risk_manager()
    gd = goal_detector or MagicMock()
    if goal_detector is None:
        gd.on_tick.return_value = GoalDetectionResult(
            goal_detected=False, confidence=0.0, reason="No spike",
        )
    if repository is None:
        repo = AsyncMock()
        repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
        repo.insert_trade.return_value = MagicMock(id=uuid.uuid4())
    else:
        repo = repository
    return LTDStrategy(
        config=cfg,
        risk_manager=rm,
        goal_detector=gd,
        repository=repo,
        run_id=RUN_ID,
    )


def _market_book_kwargs(**overrides) -> dict:
    """Build keyword arguments for on_market_book."""
    defaults = {
        "market_id": "1.23456789",
        "db_market_id": DB_MARKET_ID,
        "betfair_market_id": "1.23456789",
        "event_name": "Arsenal v Chelsea",
        "draw_selection_id": 12345,
        "draw_lay_price": Decimal("3.20"),
        "draw_back_price": Decimal("3.10"),
        "volume": 75_000,
        "timestamp": NOW,
        "kick_off": KICK_OFF,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Entry condition tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entry_all_conditions_met() -> None:
    """When all entry conditions pass, a lay order should be placed."""
    repo = AsyncMock()
    repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(repository=repo)

    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.20"),
        volume=75_000,
    ))

    repo.insert_order.assert_called_once()
    call_args = repo.insert_order.call_args
    assert call_args.kwargs["side"] == "LAY"
    assert call_args.kwargs["price"] == Decimal("3.20")
    assert call_args.kwargs["size"] == Decimal("10.00")


@pytest.mark.asyncio
async def test_entry_price_too_high() -> None:
    """Entry should be skipped when lay price exceeds max_entry_odds."""
    repo = AsyncMock()
    strategy = _make_strategy(repository=repo)

    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("4.00"),  # > max_entry_odds (3.5)
        volume=75_000,
    ))

    repo.insert_order.assert_not_called()


@pytest.mark.asyncio
async def test_entry_volume_too_low() -> None:
    """Entry should be skipped when volume is below minimum."""
    repo = AsyncMock()
    strategy = _make_strategy(repository=repo)

    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.20"),
        volume=10_000,  # < min_market_volume (50,000)
    ))

    repo.insert_order.assert_not_called()


@pytest.mark.asyncio
async def test_entry_kill_switch_active() -> None:
    """Entry should be skipped when kill switch is active."""
    rm = _make_risk_manager()
    rm.check_kill_switch.return_value = True
    repo = AsyncMock()
    strategy = _make_strategy(risk_manager=rm, repository=repo)

    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.20"),
        volume=75_000,
    ))

    repo.insert_order.assert_not_called()


@pytest.mark.asyncio
async def test_entry_already_in_position() -> None:
    """Second call with same market_id should not place a second order."""
    repo = AsyncMock()
    repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(repository=repo)

    # First call → enters position
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.20"), volume=75_000,
    ))
    assert repo.insert_order.call_count == 1

    # Second call → state is ENTERED, should skip entry
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.00"), volume=100_000,
    ))
    assert repo.insert_order.call_count == 1  # No second entry


@pytest.mark.asyncio
async def test_entry_liability_logged() -> None:
    """Liability must be calculated and logged before order placement."""
    rm = _make_risk_manager()
    rm.calculate_liability.return_value = Decimal("22.00")
    repo = AsyncMock()
    repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(risk_manager=rm, repository=repo)

    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.20"), volume=75_000,
    ))

    rm.calculate_liability.assert_called_once_with(
        Decimal("10.00"), Decimal("3.20"),
    )


# ---------------------------------------------------------------------------
# Exit condition tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exit_goal_detected() -> None:
    """Goal detection should trigger green-up and trade record."""
    gd = MagicMock()
    gd.on_tick.return_value = GoalDetectionResult(
        goal_detected=True, confidence=0.8, reason="Price spike 35%",
    )
    repo = AsyncMock()
    repo.insert_order.side_effect = [
        MagicMock(id=uuid.uuid4()),  # entry
        MagicMock(id=uuid.uuid4()),  # exit
    ]
    repo.insert_trade.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(goal_detector=gd, repository=repo)

    # Entry
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.20"), volume=75_000,
    ))
    assert repo.insert_order.call_count == 1  # entry only

    # Exit tick — goal detected
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("5.50"),  # spike after goal
        draw_back_price=Decimal("5.20"),
        volume=100_000,
    ))

    assert repo.insert_order.call_count == 2  # entry + exit
    repo.insert_trade.assert_called_once()
    # Verify exit order was BACK
    exit_call = repo.insert_order.call_args_list[1]
    assert exit_call.kwargs["side"] == "BACK"


@pytest.mark.asyncio
async def test_exit_time_stop() -> None:
    """Time stop should trigger exit at minute 65 when limit is 60."""
    repo = AsyncMock()
    repo.insert_order.side_effect = [
        MagicMock(id=uuid.uuid4()),  # entry
        MagicMock(id=uuid.uuid4()),  # exit
    ]
    repo.insert_trade.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(repository=repo)

    # Entry at minute 2 (KICK_OFF + 2 min)
    entry_time = datetime(2026, 6, 14, 15, 2, 0, tzinfo=UTC)
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.20"),
        volume=75_000,
        timestamp=entry_time,
    ))

    # Tick at minute 65 → should trigger time stop
    exit_time = datetime(2026, 6, 14, 16, 5, 0, tzinfo=UTC)
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.30"),
        draw_back_price=Decimal("3.20"),
        volume=110_000,
        timestamp=exit_time,
    ))

    assert repo.insert_order.call_count == 2
    trade_call = repo.insert_trade.call_args
    assert "Time stop" in trade_call.kwargs["exit_reason"]


@pytest.mark.asyncio
async def test_exit_pnl_stop() -> None:
    """P&L stop should trigger exit when daily P&L below limit."""
    rm = _make_risk_manager()
    rm.daily_pnl = Decimal("-75.00")  # Below -50 limit
    rm.calculate_green_up_stake.return_value = Decimal("4.00")
    rm.calculate_commission.return_value = Decimal("0.00")
    repo = AsyncMock()
    repo.insert_order.side_effect = [
        MagicMock(id=uuid.uuid4()),  # entry
        MagicMock(id=uuid.uuid4()),  # exit
    ]
    repo.insert_trade.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(risk_manager=rm, repository=repo)

    # Entry
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.20"), volume=75_000,
    ))
    # Exit (P&L already below limit, exit triggers on next tick)
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.20"), volume=80_000,
    ))

    assert repo.insert_order.call_count == 2
    trade_call = repo.insert_trade.call_args
    assert "P&L stop" in trade_call.kwargs["exit_reason"]


@pytest.mark.asyncio
async def test_no_exit_when_no_trigger() -> None:
    """When no exit trigger fires, no order should be placed."""
    repo = AsyncMock()
    repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(repository=repo)

    # Entry
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.20"), volume=75_000,
    ))
    assert repo.insert_order.call_count == 1

    # Tick with no trigger (goal detector returns false, minute is low, P&L ok)
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.25"),
        draw_back_price=Decimal("3.15"),
    ))

    assert repo.insert_order.call_count == 1  # No exit order


# ---------------------------------------------------------------------------
# State machine tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closed_market_ignored() -> None:
    """After a trade closes, further ticks should be ignored."""
    gd = MagicMock()
    gd.on_tick.return_value = GoalDetectionResult(
        goal_detected=True, confidence=1.0, reason="Goal",
    )
    repo = AsyncMock()
    repo.insert_order.side_effect = [
        MagicMock(id=uuid.uuid4()),  # entry
        MagicMock(id=uuid.uuid4()),  # exit
    ]
    repo.insert_trade.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(goal_detector=gd, repository=repo)

    # Entry + exit (goal detected)
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("3.20"), volume=75_000,
    ))
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("5.00"), volume=100_000,
    ))
    assert repo.insert_order.call_count == 2

    # Another tick on the closed market → should be ignored
    await strategy.on_market_book(**_market_book_kwargs(
        draw_lay_price=Decimal("2.00"), volume=50_000,
    ))
    assert repo.insert_order.call_count == 2  # No change


@pytest.mark.asyncio
async def test_multiple_markets_independent() -> None:
    """Two markets should have independent position states."""
    repo = AsyncMock()
    repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(repository=repo)

    # Open position on m1
    await strategy.on_market_book(**_market_book_kwargs(
        market_id="m1", draw_lay_price=Decimal("3.20"), volume=75_000,
    ))
    assert repo.insert_order.call_count == 1

    # Open position on m2 (should succeed — different market)
    await strategy.on_market_book(**_market_book_kwargs(
        market_id="m2", db_market_id=uuid.uuid4(),
        betfair_market_id="m2", event_name="Liverpool v Everton",
        draw_lay_price=Decimal("2.80"), volume=90_000,
    ))
    assert repo.insert_order.call_count == 2

    # Verify both are tracked independently
    assert "m1" in strategy._positions
    assert "m2" in strategy._positions
    assert strategy._positions["m1"].state == PositionState.ENTERED
    assert strategy._positions["m2"].state == PositionState.ENTERED


# ---------------------------------------------------------------------------
# P&L helper tests
# ---------------------------------------------------------------------------


def test_calculate_gross_pnl_profit() -> None:
    """Green-up profit when back odds > lay odds."""
    # lay £10 at 3.5, back at 10.0
    # profit = 10 × (10 - 3.5) / 10 = 10 × 6.5 / 10 = 6.50
    result = LTDStrategy._calculate_gross_pnl(
        Decimal("10.00"), Decimal("3.50"), Decimal("10.00"),
    )
    assert result == Decimal("6.50")


def test_calculate_gross_pnl_loss() -> None:
    """Green-up loss when back odds < lay odds."""
    # lay £10 at 3.5, back at 3.0
    # profit = 10 × (3 - 3.5) / 3 = 10 × -0.5 / 3 = -1.666...
    result = LTDStrategy._calculate_gross_pnl(
        Decimal("10.00"), Decimal("3.50"), Decimal("3.00"),
    )
    # ~ -1.67
    assert result < Decimal("0")
    assert abs(result - Decimal("-1.67")) < Decimal("0.01")


def test_calculate_gross_pnl_zero_back_odds() -> None:
    """Safety: zero back odds returns zero."""
    result = LTDStrategy._calculate_gross_pnl(
        Decimal("10.00"), Decimal("3.50"), Decimal("0"),
    )
    assert result == Decimal("0.00")


# ---------------------------------------------------------------------------
# Market minute helper
# ---------------------------------------------------------------------------


def test_compute_market_minute_mid_match() -> None:
    """Should compute elapsed minutes correctly."""
    kick_off = datetime(2026, 6, 14, 15, 0, 0, tzinfo=UTC)
    now = datetime(2026, 6, 14, 15, 12, 0, tzinfo=UTC)
    assert LTDStrategy._compute_market_minute(now, kick_off) == 12


def test_compute_market_minute_pre_match() -> None:
    """Should return 0 if before kick-off."""
    kick_off = datetime(2026, 6, 14, 15, 0, 0, tzinfo=UTC)
    now = datetime(2026, 6, 14, 14, 55, 0, tzinfo=UTC)
    assert LTDStrategy._compute_market_minute(now, kick_off) == 0


def test_compute_market_minute_no_kick_off() -> None:
    """Should return 0 when kick_off is None."""
    assert LTDStrategy._compute_market_minute(NOW, None) == 0
