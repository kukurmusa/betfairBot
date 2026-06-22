"""Unit tests for LTDStrategy — state machine, entry/exit logic."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.config.settings import StrategyConfig
from src.goal_detection.detector import GoalDetectionResult
from src.strategy.ltd_strategy import LTDStrategy, PositionState

# NOW is pre-match: kick-off is 28 minutes away so all default _kwargs are pre-match.
NOW = datetime(2026, 6, 14, 15, 2, 0, tzinfo=UTC)
KICK_OFF = datetime(2026, 6, 14, 15, 30, 0, tzinfo=UTC)
RUN_ID = uuid.uuid4()
DB_MARKET_ID = uuid.uuid4()


def _make_config(**overrides) -> StrategyConfig:
    defaults = dict(
        max_entry_odds=3.5, stake=10.0, commission_rate=0.05,
        goal_spike_threshold=0.30, stop_loss_minute=60,
        min_market_volume=50_000, daily_loss_limit=50.0,
        max_open_positions=3, max_liability_per_bet=5.0,
    )
    defaults.update(overrides)
    return StrategyConfig(**defaults)  # type: ignore[arg-type]


def _make_risk_manager(**overrides) -> MagicMock:
    rm = MagicMock()
    rm.check_kill_switch.return_value = False
    rm.daily_pnl = Decimal("0.00")
    rm.calculate_liability.return_value = Decimal("2.20")  # 10 × (1.22) — within 5.0 cap
    rm.calculate_green_up_stake.return_value = Decimal("3.50")
    rm.calculate_commission.return_value = Decimal("0.25")
    for key, value in overrides.items():
        setattr(rm, key, value)
    return rm


def _make_strategy(config=None, risk_manager=None, goal_detector=None, repository=None) -> LTDStrategy:
    cfg = config or _make_config()
    rm = risk_manager or _make_risk_manager()
    gd = goal_detector or MagicMock()
    if goal_detector is None:
        gd.on_tick.return_value = GoalDetectionResult(goal_detected=False, confidence=0.0, reason="No spike")
    repo = repository or MagicMock()
    if repository is None:
        repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
        repo.insert_trade.return_value = MagicMock(id=uuid.uuid4())
    return LTDStrategy(config=cfg, risk_manager=rm, goal_detector=gd, repository=repo, run_id=RUN_ID)


def _kwargs(**overrides) -> dict:
    defaults = dict(
        market_id="1.23456789", db_market_id=DB_MARKET_ID,
        betfair_market_id="1.23456789", event_name="Arsenal v Chelsea",
        draw_selection_id=12345, draw_lay_price=Decimal("3.20"),
        draw_back_price=Decimal("3.10"), volume=75_000,
        timestamp=NOW, kick_off=KICK_OFF,
    )
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Entry conditions
# ---------------------------------------------------------------------------


def test_entry_all_conditions_met() -> None:
    repo = MagicMock()
    repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(repository=repo)

    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.20"), volume=75_000))

    repo.insert_order.assert_called_once()
    call = repo.insert_order.call_args
    assert call.kwargs["side"] == "LAY"
    assert call.kwargs["price"] == Decimal("3.20")
    assert call.kwargs["size"] == Decimal("10.00")


def test_entry_price_too_high() -> None:
    repo = MagicMock()
    strategy = _make_strategy(repository=repo)
    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("4.00"), volume=75_000))
    repo.insert_order.assert_not_called()


def test_entry_volume_too_low() -> None:
    repo = MagicMock()
    strategy = _make_strategy(repository=repo)
    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.20"), volume=10_000))
    repo.insert_order.assert_not_called()


def test_entry_kill_switch_active() -> None:
    rm = _make_risk_manager()
    rm.check_kill_switch.return_value = True
    repo = MagicMock()
    strategy = _make_strategy(risk_manager=rm, repository=repo)
    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.20"), volume=75_000))
    repo.insert_order.assert_not_called()


def test_entry_already_in_position() -> None:
    repo = MagicMock()
    repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(repository=repo)

    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.20"), volume=75_000))
    assert repo.insert_order.call_count == 1

    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.00"), volume=100_000))
    assert repo.insert_order.call_count == 1


def test_entry_liability_logged() -> None:
    rm = _make_risk_manager()
    rm.calculate_liability.return_value = Decimal("2.20")
    repo = MagicMock()
    repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(risk_manager=rm, repository=repo)

    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.20"), volume=75_000))

    rm.calculate_liability.assert_called_once_with(Decimal("10.00"), Decimal("3.20"))


def test_entry_skipped_in_play() -> None:
    """Entry rejected when match has already kicked off."""
    kick_off = datetime(2026, 6, 14, 15, 0, 0, tzinfo=UTC)
    in_play = datetime(2026, 6, 14, 15, 5, 0, tzinfo=UTC)
    repo = MagicMock()
    strategy = _make_strategy(repository=repo)
    strategy.on_market_book(**_kwargs(kick_off=kick_off, timestamp=in_play,
                                      draw_lay_price=Decimal("3.20"), volume=75_000))
    repo.insert_order.assert_not_called()


def test_entry_allowed_when_kick_off_unknown() -> None:
    """When kick_off is None we cannot know if in-play, so entry is allowed."""
    repo = MagicMock()
    repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(repository=repo)
    strategy.on_market_book(**_kwargs(kick_off=None, draw_lay_price=Decimal("3.20"), volume=75_000))
    repo.insert_order.assert_called_once()


def test_entry_skipped_max_positions() -> None:
    """Entry rejected when max_open_positions cap is already reached."""
    cfg = _make_config(max_open_positions=1)
    repo = MagicMock()
    repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(config=cfg, repository=repo)

    strategy.on_market_book(**_kwargs(market_id="m1", draw_lay_price=Decimal("3.20"), volume=75_000))
    assert repo.insert_order.call_count == 1

    strategy.on_market_book(**_kwargs(
        market_id="m2", db_market_id=uuid.uuid4(), betfair_market_id="m2",
        event_name="Liverpool v Everton", draw_lay_price=Decimal("2.80"), volume=90_000,
    ))
    assert repo.insert_order.call_count == 1  # second market blocked


def test_entry_skipped_liability_too_high() -> None:
    """Entry rejected when liability exceeds max_liability_per_bet."""
    cfg = _make_config(max_liability_per_bet=4.0)
    rm = _make_risk_manager()
    rm.calculate_liability.return_value = Decimal("22.00")  # way over the 4.0 cap
    repo = MagicMock()
    strategy = _make_strategy(config=cfg, risk_manager=rm, repository=repo)
    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.20"), volume=75_000))
    repo.insert_order.assert_not_called()


# ---------------------------------------------------------------------------
# Exit conditions
# ---------------------------------------------------------------------------


def test_exit_goal_detected() -> None:
    gd = MagicMock()
    gd.on_tick.return_value = GoalDetectionResult(goal_detected=True, confidence=0.8, reason="Price spike 35%")
    repo = MagicMock()
    repo.insert_order.side_effect = [MagicMock(id=uuid.uuid4()), MagicMock(id=uuid.uuid4())]
    repo.insert_trade.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(goal_detector=gd, repository=repo)

    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.20"), volume=75_000))
    assert repo.insert_order.call_count == 1

    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("5.50"), draw_back_price=Decimal("5.20"), volume=100_000))
    assert repo.insert_order.call_count == 2
    repo.insert_trade.assert_called_once()
    assert repo.insert_order.call_args_list[1].kwargs["side"] == "BACK"
    assert repo.insert_trade.call_args.kwargs["exit_reason"] == "goal_detected"


def test_exit_time_stop() -> None:
    kick_off = datetime(2026, 6, 14, 15, 0, 0, tzinfo=UTC)
    repo = MagicMock()
    repo.insert_order.side_effect = [MagicMock(id=uuid.uuid4()), MagicMock(id=uuid.uuid4())]
    repo.insert_trade.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(repository=repo)

    # Enter pre-match (2 minutes before kick-off)
    strategy.on_market_book(**_kwargs(
        kick_off=kick_off,
        timestamp=datetime(2026, 6, 14, 14, 58, 0, tzinfo=UTC),
        draw_lay_price=Decimal("3.20"), volume=75_000,
    ))
    # Exit at minute 65 (5 min past the stop_loss_minute=60)
    strategy.on_market_book(**_kwargs(
        kick_off=kick_off,
        timestamp=datetime(2026, 6, 14, 16, 5, 0, tzinfo=UTC),
        draw_lay_price=Decimal("3.30"), draw_back_price=Decimal("3.20"), volume=110_000,
    ))

    assert repo.insert_order.call_count == 2
    assert repo.insert_trade.call_args.kwargs["exit_reason"] == "stop_loss_time"


def test_exit_kill_switch_closes_open_position() -> None:
    """When kill switch activates mid-position, the next tick must green up immediately."""
    rm = _make_risk_manager()
    repo = MagicMock()
    repo.insert_order.side_effect = [MagicMock(id=uuid.uuid4()), MagicMock(id=uuid.uuid4())]
    repo.insert_trade.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(risk_manager=rm, repository=repo)

    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.20"), volume=75_000))
    assert repo.insert_order.call_count == 1

    rm.check_kill_switch.return_value = True
    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.20"), volume=80_000))

    assert repo.insert_order.call_count == 2
    assert repo.insert_trade.call_args.kwargs["exit_reason"] == "kill_switch"


def test_no_exit_when_no_trigger() -> None:
    repo = MagicMock()
    repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(repository=repo)

    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.20"), volume=75_000))
    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.25"), draw_back_price=Decimal("3.15")))

    assert repo.insert_order.call_count == 1


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


def test_closed_market_ignored() -> None:
    gd = MagicMock()
    gd.on_tick.return_value = GoalDetectionResult(goal_detected=True, confidence=1.0, reason="Goal")
    repo = MagicMock()
    repo.insert_order.side_effect = [MagicMock(id=uuid.uuid4()), MagicMock(id=uuid.uuid4())]
    repo.insert_trade.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(goal_detector=gd, repository=repo)

    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("3.20"), volume=75_000))
    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("5.00"), volume=100_000))
    assert repo.insert_order.call_count == 2

    strategy.on_market_book(**_kwargs(draw_lay_price=Decimal("2.00"), volume=50_000))
    assert repo.insert_order.call_count == 2


def test_multiple_markets_independent() -> None:
    repo = MagicMock()
    repo.insert_order.return_value = MagicMock(id=uuid.uuid4())
    strategy = _make_strategy(repository=repo)

    strategy.on_market_book(**_kwargs(market_id="m1", draw_lay_price=Decimal("3.20"), volume=75_000))
    strategy.on_market_book(**_kwargs(
        market_id="m2", db_market_id=uuid.uuid4(), betfair_market_id="m2",
        event_name="Liverpool v Everton", draw_lay_price=Decimal("2.80"), volume=90_000,
    ))

    assert repo.insert_order.call_count == 2
    assert strategy._positions["m1"].state == PositionState.ENTERED
    assert strategy._positions["m2"].state == PositionState.ENTERED


# ---------------------------------------------------------------------------
# P&L helpers
# ---------------------------------------------------------------------------


def test_calculate_gross_pnl_profit() -> None:
    result = LTDStrategy._calculate_gross_pnl(Decimal("10.00"), Decimal("3.50"), Decimal("10.00"))
    assert result == Decimal("6.50")


def test_calculate_gross_pnl_loss() -> None:
    result = LTDStrategy._calculate_gross_pnl(Decimal("10.00"), Decimal("3.50"), Decimal("3.00"))
    assert result < Decimal("0")
    assert abs(result - Decimal("-1.67")) < Decimal("0.01")


def test_calculate_gross_pnl_zero_back_odds() -> None:
    assert LTDStrategy._calculate_gross_pnl(Decimal("10.00"), Decimal("3.50"), Decimal("0")) == Decimal("0.00")


# ---------------------------------------------------------------------------
# Market minute helper
# ---------------------------------------------------------------------------


def test_compute_market_minute_mid_match() -> None:
    kick_off = datetime(2026, 6, 14, 15, 0, 0, tzinfo=UTC)
    now = datetime(2026, 6, 14, 15, 12, 0, tzinfo=UTC)
    assert LTDStrategy._compute_market_minute(now, kick_off) == 12


def test_compute_market_minute_pre_match() -> None:
    kick_off = datetime(2026, 6, 14, 15, 0, 0, tzinfo=UTC)
    now = datetime(2026, 6, 14, 14, 55, 0, tzinfo=UTC)
    assert LTDStrategy._compute_market_minute(now, kick_off) == 0


def test_compute_market_minute_no_kick_off() -> None:
    assert LTDStrategy._compute_market_minute(NOW, None) == 0
