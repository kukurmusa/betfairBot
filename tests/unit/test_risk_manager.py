"""Unit tests for RiskManager — kill switch, liability, and P&L calculations."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.config.settings import StrategyConfig
from src.risk.risk_manager import RiskManager


def test_kill_switch_inactive_by_default() -> None:
    assert RiskManager(StrategyConfig(daily_loss_limit=50.0)).check_kill_switch() is False


def test_kill_switch_reads_daily_loss_limit_from_config() -> None:
    assert RiskManager(StrategyConfig(daily_loss_limit=100.0)).daily_loss_limit == 100.0


def test_daily_pnl_starts_at_zero() -> None:
    assert RiskManager(StrategyConfig()).daily_pnl == Decimal("0.00")


# ---------------------------------------------------------------------------
# update_pnl — kill switch activation
# ---------------------------------------------------------------------------


def test_update_pnl_activates_kill_switch_on_breach() -> None:
    rm = RiskManager(StrategyConfig(daily_loss_limit=50.0))
    rm.update_pnl(Decimal("-75.00"))
    assert rm.check_kill_switch() is True
    assert rm.daily_pnl == Decimal("-75.00")


def test_update_pnl_no_activation_within_limit() -> None:
    rm = RiskManager(StrategyConfig(daily_loss_limit=50.0))
    rm.update_pnl(Decimal("-30.00"))
    assert rm.check_kill_switch() is False


def test_update_pnl_accumulates() -> None:
    rm = RiskManager(StrategyConfig(daily_loss_limit=100.0))
    rm.update_pnl(Decimal("-40.00"))
    rm.update_pnl(Decimal("-40.00"))
    assert rm.daily_pnl == Decimal("-80.00")
    assert rm.check_kill_switch() is False

    rm.update_pnl(Decimal("-30.00"))
    assert rm.daily_pnl == Decimal("-110.00")
    assert rm.check_kill_switch() is True


def test_update_pnl_profit_reduces_loss() -> None:
    rm = RiskManager(StrategyConfig(daily_loss_limit=50.0))
    rm.update_pnl(Decimal("-40.00"))
    rm.update_pnl(Decimal("30.00"))
    assert rm.daily_pnl == Decimal("-10.00")
    assert rm.check_kill_switch() is False


# ---------------------------------------------------------------------------
# Liability calculation
# ---------------------------------------------------------------------------


def test_calculate_liability() -> None:
    rm = RiskManager(StrategyConfig())
    assert rm.calculate_liability(Decimal("10.00"), Decimal("3.50")) == Decimal("25.00")


def test_calculate_liability_low_odds() -> None:
    rm = RiskManager(StrategyConfig())
    assert rm.calculate_liability(Decimal("10.00"), Decimal("1.50")) == Decimal("5.00")


def test_calculate_liability_high_odds() -> None:
    rm = RiskManager(StrategyConfig())
    assert rm.calculate_liability(Decimal("2.00"), Decimal("10.00")) == Decimal("18.00")


# ---------------------------------------------------------------------------
# Green-up stake
# ---------------------------------------------------------------------------


def test_calculate_green_up_stake_profitable() -> None:
    rm = RiskManager(StrategyConfig())
    assert rm.calculate_green_up_stake(Decimal("10.00"), Decimal("3.50"), Decimal("10.00")) == Decimal("3.50")


def test_calculate_green_up_stake_loss() -> None:
    rm = RiskManager(StrategyConfig())
    assert rm.calculate_green_up_stake(Decimal("10.00"), Decimal("3.50"), Decimal("3.00")) == Decimal("11.67")


def test_calculate_green_up_stake_zero_back_odds() -> None:
    rm = RiskManager(StrategyConfig())
    assert rm.calculate_green_up_stake(Decimal("10.00"), Decimal("3.50"), Decimal("0")) == Decimal("0.00")


# ---------------------------------------------------------------------------
# Commission
# ---------------------------------------------------------------------------


def test_calculate_commission_on_profit() -> None:
    rm = RiskManager(StrategyConfig(commission_rate=0.05))
    assert rm.calculate_commission(Decimal("10.00"), 0.05) == Decimal("0.50")


def test_calculate_commission_on_loss() -> None:
    rm = RiskManager(StrategyConfig())
    assert rm.calculate_commission(Decimal("-5.00"), 0.05) == Decimal("0.00")


def test_calculate_commission_on_breakeven() -> None:
    rm = RiskManager(StrategyConfig())
    assert rm.calculate_commission(Decimal("0.00"), 0.05) == Decimal("0.00")


def test_calculate_commission_custom_rate() -> None:
    rm = RiskManager(StrategyConfig())
    assert rm.calculate_commission(Decimal("100.00"), 0.08) == Decimal("8.00")
