"""Unit tests for BacktestReport."""

from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.backtest.report import BacktestReport, ReportSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade(net_pnl: float, stake: float = 10.0, exit_reason: str = "stop_loss_time") -> MagicMock:
    t = MagicMock()
    t.id = uuid.uuid4()
    t.market_id = uuid.uuid4()
    t.net_pnl = net_pnl
    t.stake = stake
    t.gross_pnl = net_pnl + abs(net_pnl) * 0.05
    t.commission = abs(net_pnl) * 0.05
    t.entry_price = 3.2
    t.exit_price = 3.0
    t.exit_reason = exit_reason
    t.opened_at = "2026-06-14T14:30:00+00:00"
    t.closed_at = "2026-06-14T15:45:00+00:00"
    return t


def _make_repo(trades: list) -> MagicMock:
    repo = MagicMock()
    repo.get_trades_for_run.return_value = trades
    return repo


# ---------------------------------------------------------------------------
# generate() — empty run
# ---------------------------------------------------------------------------


def test_generate_empty_run_returns_zeroes() -> None:
    """No trades should produce a zero-value summary without error."""
    run_id = uuid.uuid4()
    summary = BacktestReport(_make_repo([])).generate(run_id)

    assert summary.total_trades == 0
    assert summary.win_count == 0
    assert summary.win_rate == 0.0
    assert summary.total_pnl == Decimal("0")
    assert summary.max_drawdown == Decimal("0")
    assert summary.sharpe_ratio == 0.0
    assert summary.roi_pct == 0.0


# ---------------------------------------------------------------------------
# generate() — win rate
# ---------------------------------------------------------------------------


def test_generate_win_rate_two_wins_one_loss() -> None:
    """2 wins out of 3 trades = 66.7% win rate."""
    trades = [_make_trade(5.0), _make_trade(3.0), _make_trade(-4.0)]
    summary = BacktestReport(_make_repo(trades)).generate(uuid.uuid4())

    assert summary.total_trades == 3
    assert summary.win_count == 2
    assert abs(summary.win_rate - 66.666) < 0.01


def test_generate_all_losses_zero_win_rate() -> None:
    """All losses → win_rate == 0.0."""
    trades = [_make_trade(-2.0), _make_trade(-3.0)]
    summary = BacktestReport(_make_repo(trades)).generate(uuid.uuid4())

    assert summary.win_count == 0
    assert summary.win_rate == 0.0


def test_generate_all_wins_100_percent() -> None:
    """All profits → win_rate == 100.0."""
    trades = [_make_trade(4.0), _make_trade(6.0)]
    summary = BacktestReport(_make_repo(trades)).generate(uuid.uuid4())

    assert summary.win_count == 2
    assert summary.win_rate == 100.0


# ---------------------------------------------------------------------------
# generate() — total / avg P&L
# ---------------------------------------------------------------------------


def test_generate_total_pnl() -> None:
    """Total P&L should be the sum of all trade net_pnl values."""
    trades = [_make_trade(3.0), _make_trade(-1.5), _make_trade(2.0)]
    summary = BacktestReport(_make_repo(trades)).generate(uuid.uuid4())

    assert summary.total_pnl == Decimal("3.5")


def test_generate_avg_pnl() -> None:
    """Avg P&L should be total / trade count."""
    trades = [_make_trade(6.0), _make_trade(2.0)]
    summary = BacktestReport(_make_repo(trades)).generate(uuid.uuid4())

    assert summary.avg_pnl == Decimal("4.0")


# ---------------------------------------------------------------------------
# generate() — max drawdown
# ---------------------------------------------------------------------------


def test_generate_max_drawdown_no_drawdown() -> None:
    """Monotonically increasing equity → drawdown is 0."""
    trades = [_make_trade(1.0), _make_trade(2.0), _make_trade(3.0)]
    summary = BacktestReport(_make_repo(trades)).generate(uuid.uuid4())

    assert summary.max_drawdown == Decimal("0")


def test_generate_max_drawdown_basic() -> None:
    """Max drawdown should equal the worst peak-to-trough decline."""
    # Cumulative: 5, 2, 4, -4, -3
    # Peak:       5, 5, 5,  5,  5
    # Drawdown:   0, 3, 1,  9,  8  → max = 9
    trades = [
        _make_trade(5.0), _make_trade(-3.0),
        _make_trade(2.0), _make_trade(-8.0),
        _make_trade(1.0),
    ]
    summary = BacktestReport(_make_repo(trades)).generate(uuid.uuid4())

    assert summary.max_drawdown == Decimal("9.0")


# ---------------------------------------------------------------------------
# generate() — Sharpe ratio
# ---------------------------------------------------------------------------


def test_generate_sharpe_zero_for_single_trade() -> None:
    """Sharpe is 0.0 when there is only one trade (no std)."""
    summary = BacktestReport(_make_repo([_make_trade(5.0)])).generate(uuid.uuid4())
    assert summary.sharpe_ratio == 0.0


def test_generate_sharpe_positive_for_positive_mean() -> None:
    """Positive mean P&L with variance → positive Sharpe."""
    trades = [_make_trade(4.0), _make_trade(2.0), _make_trade(6.0)]
    summary = BacktestReport(_make_repo(trades)).generate(uuid.uuid4())
    assert summary.sharpe_ratio > 0.0


def test_generate_sharpe_zero_for_zero_variance() -> None:
    """All identical P&L values → std = 0 → Sharpe returns 0.0 (no div-by-zero)."""
    trades = [_make_trade(3.0), _make_trade(3.0), _make_trade(3.0)]
    summary = BacktestReport(_make_repo(trades)).generate(uuid.uuid4())
    assert summary.sharpe_ratio == 0.0


# ---------------------------------------------------------------------------
# generate() — ROI
# ---------------------------------------------------------------------------


def test_generate_roi_pct() -> None:
    """ROI = total_pnl / total_staked * 100."""
    trades = [_make_trade(2.0, stake=10.0), _make_trade(3.0, stake=10.0)]
    summary = BacktestReport(_make_repo(trades)).generate(uuid.uuid4())

    # total_pnl=5, total_staked=20 → ROI = 25%
    assert abs(summary.roi_pct - 25.0) < 0.001


# ---------------------------------------------------------------------------
# to_csv()
# ---------------------------------------------------------------------------


def test_to_csv_writes_headers_and_rows(tmp_path: Path) -> None:
    """CSV output should contain headers and one row per trade."""
    trades = [_make_trade(3.0), _make_trade(-1.5)]
    repo = _make_repo(trades)
    output = tmp_path / "report.csv"

    BacktestReport(repo).to_csv(uuid.uuid4(), output)

    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("trade_id,market_id")
    assert len(lines) == 3  # header + 2 trades


def test_to_csv_empty_run_writes_header_only(tmp_path: Path) -> None:
    """Empty run still writes the header row."""
    repo = _make_repo([])
    output = tmp_path / "empty.csv"

    BacktestReport(repo).to_csv(uuid.uuid4(), output)

    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "trade_id" in lines[0]


# ---------------------------------------------------------------------------
# print_summary() — smoke test
# ---------------------------------------------------------------------------


def test_print_summary_does_not_raise(capsys: pytest.CaptureFixture) -> None:
    """print_summary should produce output without raising."""
    summary = ReportSummary(
        run_id=uuid.uuid4(), total_trades=5, win_count=3, win_rate=60.0,
        avg_pnl=Decimal("1.20"), total_pnl=Decimal("6.00"),
        max_drawdown=Decimal("2.50"), sharpe_ratio=1.5, roi_pct=12.0,
        total_staked=Decimal("50.00"),
    )
    BacktestReport(MagicMock()).print_summary(summary)

    captured = capsys.readouterr()
    assert "Total trades" in captured.out
    assert "Win rate" in captured.out
    assert "Sharpe" in captured.out
