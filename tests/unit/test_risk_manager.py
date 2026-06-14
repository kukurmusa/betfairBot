"""Unit tests for RiskManager — kill switch, liability, and P&L calculations."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.config.settings import StrategyConfig
from src.risk.risk_manager import RiskManager


def test_kill_switch_inactive_by_default() -> None:
    """Kill switch should start inactive."""
    cfg = StrategyConfig(daily_loss_limit=50.0)
    rm = RiskManager(cfg)
    assert rm.check_kill_switch() is False


def test_kill_switch_reads_daily_loss_limit_from_config() -> None:
    """RiskManager should store the configured daily loss limit."""
    cfg = StrategyConfig(daily_loss_limit=100.0)
    rm = RiskManager(cfg)
    assert rm.daily_loss_limit == 100.0


def test_daily_pnl_starts_at_zero() -> None:
    """Daily P&L should start at 0.00."""
    cfg = StrategyConfig()
    rm = RiskManager(cfg)
    assert rm.daily_pnl == Decimal("0.00")


# ---------------------------------------------------------------------------
# Phase 2 update_pnl — kill switch activation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_pnl_activates_kill_switch_on_breach() -> None:
    """Kill switch should activate when daily P&L drops below limit."""
    cfg = StrategyConfig(daily_loss_limit=50.0)
    rm = RiskManager(cfg)

    await rm.update_pnl(Decimal("-75.00"))
    assert rm.check_kill_switch() is True
    assert rm.daily_pnl == Decimal("-75.00")


@pytest.mark.asyncio
async def test_update_pnl_no_activation_within_limit() -> None:
    """Kill switch should stay inactive if loss is within limit."""
    cfg = StrategyConfig(daily_loss_limit=50.0)
    rm = RiskManager(cfg)

    await rm.update_pnl(Decimal("-30.00"))
    assert rm.check_kill_switch() is False


@pytest.mark.asyncio
async def test_update_pnl_accumulates() -> None:
    """update_pnl should accumulate across multiple calls."""
    cfg = StrategyConfig(daily_loss_limit=100.0)
    rm = RiskManager(cfg)

    await rm.update_pnl(Decimal("-40.00"))
    await rm.update_pnl(Decimal("-40.00"))
    assert rm.daily_pnl == Decimal("-80.00")
    assert rm.check_kill_switch() is False  # -80 > -100

    await rm.update_pnl(Decimal("-30.00"))
    assert rm.daily_pnl == Decimal("-110.00")
    assert rm.check_kill_switch() is True


@pytest.mark.asyncio
async def test_update_pnl_profit_reduces_loss() -> None:
    """Positive P&L should offset previous losses."""
    cfg = StrategyConfig(daily_loss_limit=50.0)
    rm = RiskManager(cfg)

    await rm.update_pnl(Decimal("-40.00"))
    await rm.update_pnl(Decimal("30.00"))
    assert rm.daily_pnl == Decimal("-10.00")
    assert rm.check_kill_switch() is False


# ---------------------------------------------------------------------------
# Liability calculation
# ---------------------------------------------------------------------------


def test_calculate_liability() -> None:
    """Liability = stake × (odds − 1)."""
    cfg = StrategyConfig()
    rm = RiskManager(cfg)

    result = rm.calculate_liability(Decimal("10.00"), Decimal("3.50"))
    # 10 × (3.5 − 1) = 10 × 2.5 = 25
    assert result == Decimal("25.00")


def test_calculate_liability_low_odds() -> None:
    """Liability with odds close to 1."""
    cfg = StrategyConfig()
    rm = RiskManager(cfg)

    result = rm.calculate_liability(Decimal("10.00"), Decimal("1.50"))
    assert result == Decimal("5.00")


def test_calculate_liability_high_odds() -> None:
    """Liability with high odds."""
    cfg = StrategyConfig()
    rm = RiskManager(cfg)

    result = rm.calculate_liability(Decimal("2.00"), Decimal("10.00"))
    # 2 × (10 - 1) = 18
    assert result == Decimal("18.00")


# ---------------------------------------------------------------------------
# Green-up stake calculation
# ---------------------------------------------------------------------------


def test_calculate_green_up_stake_profitable() -> None:
    """Green-up when back odds > lay odds (goal scenario)."""
    cfg = StrategyConfig()
    rm = RiskManager(cfg)

    # lay £10 at 3.5, back at 10.0
    # back_stake = 10 × 3.5 / 10 = 3.50
    result = rm.calculate_green_up_stake(
        Decimal("10.00"), Decimal("3.50"), Decimal("10.00"),
    )
    assert result == Decimal("3.50")


def test_calculate_green_up_stake_loss() -> None:
    """Green-up when back odds < lay odds (stop-loss scenario)."""
    cfg = StrategyConfig()
    rm = RiskManager(cfg)

    # lay £10 at 3.5, back at 3.0 → back_stake = 10 × 3.5 / 3.0 = 11.67
    result = rm.calculate_green_up_stake(
        Decimal("10.00"), Decimal("3.50"), Decimal("3.00"),
    )
    assert result == Decimal("11.67")


def test_calculate_green_up_stake_zero_back_odds() -> None:
    """Zero back odds should return zero (safety check)."""
    cfg = StrategyConfig()
    rm = RiskManager(cfg)

    result = rm.calculate_green_up_stake(
        Decimal("10.00"), Decimal("3.50"), Decimal("0"),
    )
    assert result == Decimal("0.00")


# ---------------------------------------------------------------------------
# Commission calculation
# ---------------------------------------------------------------------------


def test_calculate_commission_on_profit() -> None:
    """Commission on a profitable trade."""
    cfg = StrategyConfig(commission_rate=0.05)
    rm = RiskManager(cfg)

    result = rm.calculate_commission(Decimal("10.00"), 0.05)
    assert result == Decimal("0.50")


def test_calculate_commission_on_loss() -> None:
    """Commission on a losing trade should be zero."""
    cfg = StrategyConfig()
    rm = RiskManager(cfg)

    result = rm.calculate_commission(Decimal("-5.00"), 0.05)
    assert result == Decimal("0.00")


def test_calculate_commission_on_breakeven() -> None:
    """Commission at breakeven should be zero."""
    cfg = StrategyConfig()
    rm = RiskManager(cfg)

    result = rm.calculate_commission(Decimal("0.00"), 0.05)
    assert result == Decimal("0.00")


def test_calculate_commission_custom_rate() -> None:
    """Commission with a non-default rate."""
    cfg = StrategyConfig()
    rm = RiskManager(cfg)

    result = rm.calculate_commission(Decimal("100.00"), 0.08)
    assert result == Decimal("8.00")
