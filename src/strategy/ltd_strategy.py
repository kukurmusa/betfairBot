"""Lay-the-Draw (LTD) strategy implementation.

Core state machine that evaluates entry and exit conditions on every
market book update.  Orchestrates goal detection, stop-loss checks, and
risk management through delegation — no Betfair API calls or raw SQL
inline.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto

from src.config.settings import StrategyConfig
from src.db.repository import Repository
from src.goal_detection.detector import GoalDetector
from src.risk.risk_manager import RiskManager
from src.risk.stop_loss import check_pnl_stop, check_time_stop

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Position state machine
# ---------------------------------------------------------------------------


class PositionState(Enum):
    """States a single market position can be in."""

    NONE = auto()     # No position — evaluate entry
    ENTERED = auto()  # Lay order placed and matched — evaluate exit
    EXITING = auto()  # Exit order placed, awaiting match (paper: skip)
    CLOSED = auto()   # Trade complete — ignore further ticks


@dataclass
class _Position:
    """Per-market position tracking."""

    market_id: str
    db_market_id: uuid.UUID
    betfair_market_id: str
    event_name: str
    draw_selection_id: int
    state: PositionState = PositionState.NONE
    entry_lay_price: Decimal | None = None
    entry_stake: Decimal | None = None
    entry_order_id: uuid.UUID | None = None
    entry_timestamp: datetime | None = None
    kick_off: datetime | None = None
    exit_back_price: Decimal | None = None
    exit_stake: Decimal | None = None
    exit_order_id: uuid.UUID | None = None


# ---------------------------------------------------------------------------
# LTD Strategy
# ---------------------------------------------------------------------------


class LTDStrategy:
    """Lay-the-Draw strategy — one instance per bot run.

    Receives market book callbacks from ``MarketStream``, evaluates
    entry and exit conditions, and manages per-market position state.

    All config values are injected; no hardcoded numbers.  All I/O
    goes through ``Repository`` and ``RiskManager``.
    """

    def __init__(
        self,
        config: StrategyConfig,
        risk_manager: RiskManager,
        goal_detector: GoalDetector,
        repository: Repository,
        run_id: uuid.UUID,
    ) -> None:
        self._config = config
        self._risk_manager = risk_manager
        self._goal_detector = goal_detector
        self._repository = repository
        self._run_id = run_id

        # Per-market position state
        self._positions: dict[str, _Position] = {}

    # ------------------------------------------------------------------
    # Public callback — called by MarketStream
    # ------------------------------------------------------------------

    async def on_market_book(
        self,
        market_id: str,
        db_market_id: uuid.UUID,
        betfair_market_id: str,
        event_name: str,
        draw_selection_id: int,
        draw_lay_price: Decimal,
        draw_back_price: Decimal,
        volume: int,
        timestamp: datetime,
        kick_off: datetime | None = None,
    ) -> None:
        """Process a market book update for strategy decisions.

        Called by ``MarketStream._handle_market_book`` after tick
        persistence.  Must not raise — all errors are logged and
        swallowed so the streaming loop is never interrupted.
        """
        # Ensure position tracking exists
        if market_id not in self._positions:
            self._positions[market_id] = _Position(
                market_id=market_id,
                db_market_id=db_market_id,
                betfair_market_id=betfair_market_id,
                event_name=event_name,
                draw_selection_id=draw_selection_id,
                kick_off=kick_off,
            )

        position = self._positions[market_id]

        try:
            if position.state == PositionState.NONE:
                await self._evaluate_entry(
                    position, draw_lay_price, volume, timestamp
                )
            elif position.state == PositionState.ENTERED:
                await self._evaluate_exit(
                    position, draw_lay_price, draw_back_price, timestamp
                )
            # EXITING and CLOSED: no action
        except Exception:
            logger.exception(
                "Strategy error for market %s (%s)", market_id, event_name
            )

    # ------------------------------------------------------------------
    # Entry logic
    # ------------------------------------------------------------------

    async def _evaluate_entry(
        self,
        position: _Position,
        draw_lay_price: Decimal,
        volume: int,
        timestamp: datetime,
    ) -> None:
        """Check entry conditions and place a lay order if all pass.

        Conditions (all must be true):
        1. Draw lay price ≤ ``max_entry_odds``
        2. Market volume ≥ ``min_market_volume``
        3. Kill switch is not active
        4. No position already open (enforced by state machine)
        """
        # Condition 1: price check
        max_odds = Decimal(str(self._config.max_entry_odds))
        if draw_lay_price > max_odds:
            return

        # Condition 2: volume check
        if volume < self._config.min_market_volume:
            return

        # Condition 3: kill switch
        if self._risk_manager.check_kill_switch():
            logger.warning(
                "Entry skipped — kill switch active: %s", position.event_name
            )
            return

        # Condition 4 is enforced by state == NONE

        stake = Decimal(str(self._config.stake))

        # ---- Liability calculation (mandatory pre-order) ----
        liability = self._risk_manager.calculate_liability(
            stake, draw_lay_price
        )
        logger.info(
            "ENTRY | %s | Lay %.2f | Stake GBP %.2f | Liability GBP %.2f",
            position.event_name,
            draw_lay_price,
            stake,
            liability,
        )

        # ---- Place lay order ----
        order = await self._repository.insert_order(
            market_id=position.db_market_id,
            run_id=self._run_id,
            side="LAY",
            price=draw_lay_price,
            size=stake,
            status="matched",  # paper mode: immediate fill
            betfair_bet_id=f"paper_{uuid.uuid4().hex[:12]}",
        )

        # ---- Update state ----
        position.state = PositionState.ENTERED
        position.entry_lay_price = draw_lay_price
        position.entry_stake = stake
        position.entry_order_id = order.id
        position.entry_timestamp = timestamp

        # ---- Initialise goal detector with reference price ----
        self._goal_detector.init_market(position.market_id, draw_lay_price)

        logger.info(
            "Position OPEN | %s @ %.2f | order=%s",
            position.event_name,
            draw_lay_price,
            order.id,
        )

    # ------------------------------------------------------------------
    # Exit logic
    # ------------------------------------------------------------------

    async def _evaluate_exit(
        self,
        position: _Position,
        draw_lay_price: Decimal,
        draw_back_price: Decimal,
        timestamp: datetime,
    ) -> None:
        """Check exit conditions and green-up if any trigger fires.

        Exit triggers (priority order):
        1. Goal detected (price spike ≥ threshold)
        2. Time stop (match minute ≥ configured limit)
        3. P&L stop (daily loss limit breached)
        """
        assert position.entry_lay_price is not None
        assert position.entry_stake is not None

        # 1. Goal detection
        goal_result = self._goal_detector.on_tick(
            position.market_id, draw_lay_price, draw_back_price, timestamp
        )

        # 2. Time stop
        market_minute = self._compute_market_minute(
            timestamp, position.kick_off
        )
        time_result = check_time_stop(
            market_minute, self._config.stop_loss_minute
        )

        # 3. P&L stop (uses running daily P&L, not per-position)
        pnl_result = check_pnl_stop(
            self._risk_manager.daily_pnl, self._config.daily_loss_limit
        )

        # ---- Determine exit reason (priority order) ----
        exit_reason: str | None = None
        if goal_result.goal_detected:
            exit_reason = f"goal_detected_{goal_result.reason}"
        elif time_result.should_exit:
            exit_reason = time_result.reason
        elif pnl_result.should_exit:
            exit_reason = pnl_result.reason

        if exit_reason is None:
            return

        # ---- Execute green-up ----
        await self._green_up(position, draw_back_price, exit_reason, timestamp)

    async def _green_up(
        self,
        position: _Position,
        draw_back_price: Decimal,
        exit_reason: str,
        timestamp: datetime,  # noqa: ARG002  reserved for future use
    ) -> None:
        """Place the exit back order and record the trade.

        Args:
            position: The open position to close.
            draw_back_price: Current best back price for green-up.
            exit_reason: Reason string for the exit.
        """
        assert position.entry_lay_price is not None
        assert position.entry_stake is not None

        # Calculate green-up stake
        back_stake = self._risk_manager.calculate_green_up_stake(
            position.entry_stake, position.entry_lay_price, draw_back_price
        )

        logger.info(
            "EXIT | %s | Reason: %s | Back %.2f | Stake GBP %.2f",
            position.event_name,
            exit_reason,
            draw_back_price,
            back_stake,
        )

        # Place back order
        exit_order = await self._repository.insert_order(
            market_id=position.db_market_id,
            run_id=self._run_id,
            side="BACK",
            price=draw_back_price,
            size=back_stake,
            status="matched",
        )

        # ---- P&L calculation ----
        # Green-up profit per outcome:
        #   profit = lay_stake × (back_odds - lay_odds) / back_odds
        gross_pnl = self._calculate_gross_pnl(
            position.entry_stake, position.entry_lay_price, draw_back_price
        )
        commission = self._risk_manager.calculate_commission(
            gross_pnl, self._config.commission_rate
        )
        net_pnl = gross_pnl - commission

        # Record trade
        trade = await self._repository.insert_trade(
            market_id=position.db_market_id,
            run_id=self._run_id,
            entry_order_id=position.entry_order_id,
            entry_price=position.entry_lay_price,
            stake=position.entry_stake,
            exit_order_id=exit_order.id,
            exit_price=draw_back_price,
            gross_pnl=gross_pnl,
            commission=commission,
            net_pnl=net_pnl,
            exit_reason=exit_reason,
        )

        # Update risk manager P&L
        await self._risk_manager.update_pnl(net_pnl)

        # Clean up goal detector
        self._goal_detector.reset_market(position.market_id)

        # Mark closed
        position.state = PositionState.CLOSED
        position.exit_back_price = draw_back_price
        position.exit_stake = back_stake
        position.exit_order_id = exit_order.id

        logger.info(
            "Trade CLOSED | %s | Gross %.2f | Commission %.2f | Net %.2f | %s",
            position.event_name,
            gross_pnl,
            commission,
            net_pnl,
            exit_reason,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_market_minute(
        current_time: datetime,
        kick_off: datetime | None,
    ) -> int:
        """Estimate the current match minute.

        Args:
            current_time: The current UTC timestamp.
            kick_off: The scheduled kick-off time (may be None).

        Returns:
            Elapsed minutes since kick-off, or 0 if pre-match or unknown.
        """
        if kick_off is None:
            return 0
        elapsed = (current_time - kick_off).total_seconds()
        if elapsed <= 0:
            return 0
        return int(elapsed / 60)

    @staticmethod
    def _calculate_gross_pnl(
        lay_stake: Decimal,
        lay_odds: Decimal,
        back_odds: Decimal,
    ) -> Decimal:
        """Compute gross P&L for the green-up.

        Equal-profit formula::

            profit = lay_stake × (back_odds − lay_odds) / back_odds

        Positive profit = goal correctly detected and odds spiked.
        Negative profit = time stop-loss (odds drifted against us).
        """
        if back_odds == Decimal("0"):
            return Decimal("0")
        return lay_stake * (back_odds - lay_odds) / back_odds
