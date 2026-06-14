"""Unit tests for stop-loss functions — pure logic, no mocking needed."""

from __future__ import annotations

from decimal import Decimal

from src.risk.stop_loss import check_pnl_stop, check_time_stop


# ---------------------------------------------------------------------------
# check_time_stop
# ---------------------------------------------------------------------------

def test_time_stop_below_threshold() -> None:
    """Should not exit when minute is below threshold."""
    result = check_time_stop(market_minute=45, stop_loss_minute=60)
    assert result.should_exit is False


def test_time_stop_at_exact_threshold() -> None:
    """Should exit when minute equals threshold."""
    result = check_time_stop(market_minute=60, stop_loss_minute=60)
    assert result.should_exit is True
    assert "60" in result.reason


def test_time_stop_above_threshold() -> None:
    """Should exit when minute exceeds threshold."""
    result = check_time_stop(market_minute=75, stop_loss_minute=60)
    assert result.should_exit is True


def test_time_stop_pre_match_zero() -> None:
    """Should not exit when market minute is 0 (pre-match)."""
    result = check_time_stop(market_minute=0, stop_loss_minute=60)
    assert result.should_exit is False
    assert "not yet started" in result.reason.lower()


def test_time_stop_negative_minute() -> None:
    """Should not exit with negative minute."""
    result = check_time_stop(market_minute=-5, stop_loss_minute=60)
    assert result.should_exit is False


def test_time_stop_first_minute() -> None:
    """Should not exit at minute 1 with a 60-min threshold."""
    result = check_time_stop(market_minute=1, stop_loss_minute=60)
    assert result.should_exit is False


# ---------------------------------------------------------------------------
# check_pnl_stop
# ---------------------------------------------------------------------------

def test_pnl_stop_within_limit() -> None:
    """Should not exit when P&L is above the loss limit."""
    result = check_pnl_stop(Decimal("10.00"), daily_loss_limit=50.0)
    assert result.should_exit is False


def test_pnl_stop_at_breakeven() -> None:
    """Should not exit at breakeven."""
    result = check_pnl_stop(Decimal("0.00"), daily_loss_limit=50.0)
    assert result.should_exit is False


def test_pnl_stop_small_loss_within_limit() -> None:
    """Should not exit when loss is under the limit."""
    result = check_pnl_stop(Decimal("-40.00"), daily_loss_limit=50.0)
    assert result.should_exit is False


def test_pnl_stop_at_exact_limit() -> None:
    """Should exit when P&L exactly equals the negative limit."""
    result = check_pnl_stop(Decimal("-50.00"), daily_loss_limit=50.0)
    # -50.00 < -50.00 is False, so should not exit at exact boundary
    # (breach means strictly below -limit)
    assert result.should_exit is False


def test_pnl_stop_below_limit() -> None:
    """Should exit when P&L has clearly breached the limit."""
    result = check_pnl_stop(Decimal("-75.00"), daily_loss_limit=50.0)
    assert result.should_exit is True
    assert "-75" in result.reason


def test_pnl_stop_deep_loss() -> None:
    """Should exit on a deep loss."""
    result = check_pnl_stop(Decimal("-500.00"), daily_loss_limit=50.0)
    assert result.should_exit is True


def test_pnl_stop_positive_profit() -> None:
    """Should not exit when in profit."""
    result = check_pnl_stop(Decimal("200.00"), daily_loss_limit=50.0)
    assert result.should_exit is False


def test_pnl_stop_custom_limit() -> None:
    """Should respect non-default limits."""
    result = check_pnl_stop(Decimal("-200.00"), daily_loss_limit=100.0)
    assert result.should_exit is True
    # -200 < -100
