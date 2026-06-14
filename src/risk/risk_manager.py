"""Risk manager — kill switch and position sizing.

Phase 1 stub: always returns safe defaults. Real logic added in Phase 3+
when live and paper trading orders are placed.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from src.config.settings import StrategyConfig

logger = logging.getLogger(__name__)


class RiskManager:
    """Central risk controller.

    In Phase 1 this is a pass-through stub that never blocks.
    Phase 2+ will implement:
    - Cumulative daily P&L tracking
    - Kill switch activation when ``daily_loss_limit`` is breached
    - Position sizing checks (max simultaneous markets)
    - Liability calculation before every order
    """

    def __init__(self, config: StrategyConfig) -> None:
        self._daily_loss_limit = config.daily_loss_limit
        self._kill_switch_active = False
        self._daily_pnl = Decimal("0.00")

    def check_kill_switch(self) -> bool:
        """Return True if all trading should be halted.

        Checks cumulative daily P&L against the configured loss limit.
        """
        return self._kill_switch_active

    def calculate_liability(
        self, stake: Decimal, lay_odds: Decimal
    ) -> Decimal:
        """Compute the liability for a lay bet.

        Liability is the amount the trader stands to lose if the
        selection wins (i.e. the draw happens)::

            liability = stake × (lay_odds − 1)

        Args:
            stake: The lay stake in GBP.
            lay_odds: The lay price expressed as decimal odds.

        Returns:
            The liability amount as a Decimal.
        """
        return stake * (lay_odds - Decimal("1"))

    def calculate_green_up_stake(
        self,
        lay_stake: Decimal,
        lay_odds: Decimal,
        back_odds: Decimal,
    ) -> Decimal:
        """Compute the back stake that equalises profit across all outcomes.

        Derived from::

            back_stake = lay_stake × lay_odds / back_odds

        This ensures the same net result regardless of whether the draw
        happens or not.

        Args:
            lay_stake: The original lay stake in GBP.
            lay_odds: The lay price at entry.
            back_odds: The current back price for the draw runner.

        Returns:
            The back stake amount, rounded to the nearest penny.
        """
        if back_odds == Decimal("0"):
            return Decimal("0")
        raw = lay_stake * lay_odds / back_odds
        return raw.quantize(Decimal("0.01"))

    def calculate_commission(
        self, gross_pnl: Decimal, commission_rate: float
    ) -> Decimal:
        """Compute Betfair commission on a gross P&L.

        Commission is calculated on gross profit only (Betfair does not
        charge commission on losing trades, but for simplicity we apply
        the rate to the absolute gross P&L).

        Args:
            gross_pnl: Gross profit/loss before commission.
            commission_rate: The Betfair commission rate (e.g. 0.05).

        Returns:
            The commission amount as a non-negative Decimal.
        """
        if gross_pnl <= Decimal("0"):
            return Decimal("0")
        raw = gross_pnl * Decimal(str(commission_rate))
        return raw.quantize(Decimal("0.01"))

    async def update_pnl(self, pnl: Decimal) -> None:
        """Update the running daily P&L and re-evaluate the kill switch.

        Accumulates P&L and activates the kill switch if the daily loss
        limit is breached.  The kill switch, once activated, stays active
        until the next calendar day (midnight UTC reset) or manual restart.

        Args:
            pnl: Net P&L from a closed trade (positive = profit).
        """
        self._daily_pnl += pnl
        logger.info("Daily P&L updated: %s (change: %s)", self._daily_pnl, pnl)

        if self._daily_pnl < -Decimal(str(self._daily_loss_limit)):
            if not self._kill_switch_active:
                self._kill_switch_active = True
                logger.critical(
                    "KILL SWITCH ACTIVATED: daily P&L %s below limit -%s",
                    self._daily_pnl,
                    self._daily_loss_limit,
                )

    @property
    def daily_pnl(self) -> Decimal:
        """Current cumulative daily P&L."""
        return self._daily_pnl

    @property
    def daily_loss_limit(self) -> float:
        """Configured daily loss limit in GBP."""
        return self._daily_loss_limit
