"""Backtest report generator — summary statistics and CSV export."""

from __future__ import annotations

import csv
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from statistics import mean, stdev

from src.db.repository import Repository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportSummary:
    """Aggregate statistics for a completed backtest run."""

    run_id: uuid.UUID
    total_trades: int
    win_count: int
    win_rate: float
    avg_pnl: Decimal
    total_pnl: Decimal
    max_drawdown: Decimal
    sharpe_ratio: float
    roi_pct: float
    total_staked: Decimal


class BacktestReport:
    """Generate summary statistics and CSV from a completed backtest run."""

    def __init__(self, repository: Repository) -> None:
        """Initialise with a DB repository."""
        self._repository = repository

    def generate(self, run_id: uuid.UUID) -> ReportSummary:
        """Compute aggregate P&L statistics for all trades in the run."""
        trades = self._repository.get_trades_for_run(run_id)
        if not trades:
            return self._empty_summary(run_id)

        pnls = [Decimal(str(t.net_pnl or 0)) for t in trades]
        stakes = [Decimal(str(t.stake or 0)) for t in trades]
        total_pnl = sum(pnls, Decimal("0"))
        total_staked = sum(stakes, Decimal("0"))
        win_count = sum(1 for p in pnls if p > 0)
        win_rate = (win_count / len(pnls)) * 100
        avg_pnl = total_pnl / len(pnls)
        roi_pct = float(total_pnl / total_staked * 100) if total_staked else 0.0

        return ReportSummary(
            run_id=run_id,
            total_trades=len(pnls),
            win_count=win_count,
            win_rate=win_rate,
            avg_pnl=avg_pnl,
            total_pnl=total_pnl,
            max_drawdown=self._compute_max_drawdown(pnls),
            sharpe_ratio=self._compute_sharpe(pnls),
            roi_pct=roi_pct,
            total_staked=total_staked,
        )

    def print_summary(self, summary: ReportSummary) -> None:
        """Print a human-readable report to stdout."""
        sep = "=" * 52
        print(f"\n{sep}")
        print(f"  Backtest Report — run {summary.run_id}")
        print(sep)
        print(f"  Total trades  : {summary.total_trades}")
        print(f"  Win rate      : {summary.win_rate:.1f}%  ({summary.win_count} wins)")
        print(f"  Avg P&L/trade : £{summary.avg_pnl:+.4f}")
        print(f"  Total P&L     : £{summary.total_pnl:+.4f}")
        print(f"  Total staked  : £{summary.total_staked:.4f}")
        print(f"  ROI           : {summary.roi_pct:+.2f}%")
        print(f"  Max drawdown  : £{summary.max_drawdown:.4f}")
        print(f"  Sharpe ratio  : {summary.sharpe_ratio:.3f}")
        print(f"{sep}\n")

    def to_csv(self, run_id: uuid.UUID, output_path: Path) -> None:
        """Export all trades for the run to a CSV file at output_path."""
        trades = self._repository.get_trades_for_run(run_id)
        fieldnames = [
            "trade_id", "market_id", "entry_price", "exit_price",
            "stake", "gross_pnl", "commission", "net_pnl",
            "exit_reason", "opened_at", "closed_at",
        ]
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for trade in trades:
                writer.writerow({
                    "trade_id": trade.id,
                    "market_id": trade.market_id,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "stake": trade.stake,
                    "gross_pnl": trade.gross_pnl,
                    "commission": trade.commission,
                    "net_pnl": trade.net_pnl,
                    "exit_reason": trade.exit_reason,
                    "opened_at": trade.opened_at,
                    "closed_at": trade.closed_at,
                })
        logger.info("CSV written: %s (%d rows)", output_path, len(trades))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_summary(run_id: uuid.UUID) -> ReportSummary:
        """Return a zero-value summary when no trades exist."""
        return ReportSummary(
            run_id=run_id, total_trades=0, win_count=0, win_rate=0.0,
            avg_pnl=Decimal("0"), total_pnl=Decimal("0"),
            max_drawdown=Decimal("0"), sharpe_ratio=0.0, roi_pct=0.0,
            total_staked=Decimal("0"),
        )

    @staticmethod
    def _compute_max_drawdown(pnls: list[Decimal]) -> Decimal:
        """Max peak-to-trough drop in cumulative P&L across the trade sequence."""
        if not pnls:
            return Decimal("0")
        peak = running = max_dd = Decimal("0")
        for p in pnls:
            running += p
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @staticmethod
    def _compute_sharpe(pnls: list[Decimal]) -> float:
        """Per-trade Sharpe: mean(net_pnl) / std(net_pnl). Returns 0 if < 2 trades."""
        if len(pnls) < 2:
            return 0.0
        floats = [float(p) for p in pnls]
        sigma = stdev(floats)
        return mean(floats) / sigma if sigma else 0.0
