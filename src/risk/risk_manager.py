"""Risk manager — kill switch, liability, and position sizing."""

from __future__ import annotations

import logging
from decimal import Decimal

from src.config.settings import StrategyConfig

logger = logging.getLogger(__name__)


class RiskManager:
    """Central risk controller."""

    def __init__(self, config: StrategyConfig) -> None:
        self._daily_loss_limit = config.daily_loss_limit
        self._kill_switch_active = False
        self._daily_pnl = Decimal("0.00")

    def check_kill_switch(self) -> bool:
        """Return True if all trading should be halted."""
        return self._kill_switch_active

    def calculate_liability(self, stake: Decimal, lay_odds: Decimal) -> Decimal:
        """Compute lay bet liability: stake × (lay_odds − 1)."""
        return stake * (lay_odds - Decimal("1"))

    def calculate_green_up_stake(
        self, lay_stake: Decimal, lay_odds: Decimal, back_odds: Decimal
    ) -> Decimal:
        """Back stake that equalises profit: lay_stake × lay_odds / back_odds."""
        if back_odds == Decimal("0"):
            return Decimal("0")
        return (lay_stake * lay_odds / back_odds).quantize(Decimal("0.01"))

    def calculate_commission(self, gross_pnl: Decimal, commission_rate: float) -> Decimal:
        """Betfair commission on gross profit (zero on losses)."""
        if gross_pnl <= Decimal("0"):
            return Decimal("0")
        return (gross_pnl * Decimal(str(commission_rate))).quantize(Decimal("0.01"))

    def update_pnl(self, pnl: Decimal) -> None:
        """Accumulate daily P&L and activate kill switch if limit is breached."""
        self._daily_pnl += pnl
        logger.info("Daily P&L: %s (change: %s)", self._daily_pnl, pnl)
        if not self._kill_switch_active and self._daily_pnl < -Decimal(str(self._daily_loss_limit)):
            self._kill_switch_active = True
            logger.critical(
                "KILL SWITCH ACTIVATED: daily P&L %s below limit -%s",
                self._daily_pnl, self._daily_loss_limit,
            )

    @property
    def daily_pnl(self) -> Decimal:
        """Current cumulative daily P&L."""
        return self._daily_pnl

    @property
    def daily_loss_limit(self) -> float:
        """Configured daily loss limit in GBP."""
        return self._daily_loss_limit
