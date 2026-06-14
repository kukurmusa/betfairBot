"""Stop-loss checks — time-based and P&L-based exit triggers.

These are stateless pure functions: the caller passes the relevant
values each tick.  No I/O, no hidden state — trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class StopLossResult:
    """Outcome of a stop-loss evaluation.

    Attributes:
        should_exit: ``True`` if the position should be closed.
        reason: Human-readable reason string.
    """

    should_exit: bool
    reason: str


def check_time_stop(
    market_minute: int,
    stop_loss_minute: int,
) -> StopLossResult:
    """Signal exit when the match has reached the configured time threshold.

    Args:
        market_minute: Current elapsed match minute (0 = pre-match).
        stop_loss_minute: Configured stop-loss minute from config.

    Returns:
        ``StopLossResult`` with ``should_exit=True`` when
        ``market_minute >= stop_loss_minute``.
    """
    if market_minute <= 0:
        return StopLossResult(
            should_exit=False,
            reason="Match not yet started — no time stop",
        )
    if market_minute >= stop_loss_minute:
        return StopLossResult(
            should_exit=True,
            reason=(
                f"Time stop: market minute {market_minute} "
                f">= limit {stop_loss_minute}"
            ),
        )
    return StopLossResult(
        should_exit=False,
        reason=f"Market minute {market_minute} below limit {stop_loss_minute}",
    )


def check_pnl_stop(
    current_pnl: Decimal,
    daily_loss_limit: float,
) -> StopLossResult:
    """Signal exit when daily P&L has breached the loss limit.

    Args:
        current_pnl: Running cumulative daily P&L from the risk manager.
        daily_loss_limit: Maximum allowed daily loss in GBP.

    Returns:
        ``StopLossResult`` with ``should_exit=True`` when
        ``current_pnl < -daily_loss_limit``.
    """
    loss_threshold = Decimal(str(-daily_loss_limit))
    if current_pnl < loss_threshold:
        return StopLossResult(
            should_exit=True,
            reason=(
                f"P&L stop: daily P&L {current_pnl} below limit "
                f"-GBP {daily_loss_limit:.2f}"
            ),
        )
    return StopLossResult(
        should_exit=False,
        reason=(
            f"Daily P&L {current_pnl} within limit "
            f"-GBP {daily_loss_limit:.2f}"
        ),
    )
