"""Lay-the-Draw (LTD) strategy — entry/exit state machine.

Pure business logic. No Betfair API calls or raw SQL inline.
All config values are injected; no hardcoded numbers.
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
from src.risk.stop_loss import check_time_stop

logger = logging.getLogger(__name__)

# Spec-defined exit reason enum values (Section 3.5).
_EXIT_GOAL = "goal_detected"
_EXIT_TIME = "stop_loss_time"
_EXIT_KILL = "kill_switch"


class PositionState(Enum):
    NONE = auto()
    ENTERED = auto()
    EXITING = auto()
    CLOSED = auto()


@dataclass
class _Position:
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


class LTDStrategy:
    """Lay-the-Draw strategy — one instance per bot run."""

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
        self._positions: dict[str, _Position] = {}

    def on_market_book(
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

        Must not raise — errors are logged so the stream is never interrupted.
        """
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
                self._evaluate_entry(position, draw_lay_price, volume, timestamp)
            elif position.state == PositionState.ENTERED:
                self._evaluate_exit(position, draw_lay_price, draw_back_price, timestamp)
        except Exception:
            logger.exception("Strategy error for market %s (%s)", market_id, event_name)

    def _evaluate_entry(
        self,
        position: _Position,
        draw_lay_price: Decimal,
        volume: int,
        timestamp: datetime,
    ) -> None:
        """Check entry conditions and place a lay order if all pass."""
        # Pre-match only — reject if kick_off is known and match has started
        if position.kick_off is not None and timestamp >= position.kick_off:
            return
        if draw_lay_price > Decimal(str(self._config.max_entry_odds)):
            return
        if volume < self._config.min_market_volume:
            return
        if self._risk_manager.check_kill_switch():
            logger.warning("Entry skipped — kill switch active: %s", position.event_name)
            return
        open_count = sum(1 for p in self._positions.values() if p.state == PositionState.ENTERED)
        if open_count >= self._config.max_open_positions:
            logger.debug(
                "Entry skipped — max positions (%d) reached: %s",
                self._config.max_open_positions, position.event_name,
            )
            return

        stake = Decimal(str(self._config.stake))
        liability = self._risk_manager.calculate_liability(stake, draw_lay_price)
        if liability > Decimal(str(self._config.max_liability_per_bet)):
            logger.warning(
                "Entry skipped — liability %.2f exceeds cap %.2f: %s",
                liability, self._config.max_liability_per_bet, position.event_name,
            )
            return

        logger.info(
            "ENTRY | %s | Lay %.2f | Stake GBP %.2f | Liability GBP %.2f",
            position.event_name, draw_lay_price, stake, liability,
        )

        order = self._repository.insert_order(
            market_id=position.db_market_id,
            run_id=self._run_id,
            side="LAY",
            price=draw_lay_price,
            size=stake,
            status="matched",
            betfair_bet_id=f"paper_{uuid.uuid4().hex[:12]}",
        )

        position.state = PositionState.ENTERED
        position.entry_lay_price = draw_lay_price
        position.entry_stake = stake
        position.entry_order_id = order.id
        position.entry_timestamp = timestamp
        self._goal_detector.init_market(position.market_id, draw_lay_price)
        logger.info("Position OPEN | %s @ %.2f | order=%s", position.event_name, draw_lay_price, order.id)

    def _evaluate_exit(
        self,
        position: _Position,
        draw_lay_price: Decimal,
        draw_back_price: Decimal,
        timestamp: datetime,
    ) -> None:
        """Check exit conditions and green-up if any trigger fires."""
        assert position.entry_lay_price is not None
        assert position.entry_stake is not None

        # Kill switch takes absolute priority — back the position immediately
        if self._risk_manager.check_kill_switch():
            self._green_up(position, draw_back_price, _EXIT_KILL)
            return

        goal_result = self._goal_detector.on_tick(position.market_id, draw_lay_price, draw_back_price, timestamp)
        market_minute = self._compute_market_minute(timestamp, position.kick_off)
        time_result = check_time_stop(market_minute, self._config.stop_loss_minute)

        exit_reason: str | None = None
        if goal_result.goal_detected:
            exit_reason = _EXIT_GOAL
        elif time_result.should_exit:
            exit_reason = _EXIT_TIME

        if exit_reason is None:
            return

        self._green_up(position, draw_back_price, exit_reason)

    def _green_up(self, position: _Position, draw_back_price: Decimal, exit_reason: str) -> None:
        """Place the exit back order and record the trade."""
        assert position.entry_lay_price is not None
        assert position.entry_stake is not None

        back_stake = self._risk_manager.calculate_green_up_stake(
            position.entry_stake, position.entry_lay_price, draw_back_price
        )
        logger.info(
            "EXIT | %s | Reason: %s | Back %.2f | Stake GBP %.2f",
            position.event_name, exit_reason, draw_back_price, back_stake,
        )

        exit_order = self._repository.insert_order(
            market_id=position.db_market_id,
            run_id=self._run_id,
            side="BACK",
            price=draw_back_price,
            size=back_stake,
            status="matched",
        )

        gross_pnl = self._calculate_gross_pnl(position.entry_stake, position.entry_lay_price, draw_back_price)
        commission = self._risk_manager.calculate_commission(gross_pnl, self._config.commission_rate)
        net_pnl = gross_pnl - commission

        self._repository.insert_trade(
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

        self._risk_manager.update_pnl(net_pnl)
        self._goal_detector.reset_market(position.market_id)

        position.state = PositionState.CLOSED
        position.exit_back_price = draw_back_price
        position.exit_stake = back_stake
        position.exit_order_id = exit_order.id

        logger.info(
            "Trade CLOSED | %s | Gross %.2f | Commission %.2f | Net %.2f | %s",
            position.event_name, gross_pnl, commission, net_pnl, exit_reason,
        )

    @staticmethod
    def _compute_market_minute(current_time: datetime, kick_off: datetime | None) -> int:
        """Elapsed minutes since kick-off, or 0 if pre-match or unknown."""
        if kick_off is None:
            return 0
        elapsed = (current_time - kick_off).total_seconds()
        return max(0, int(elapsed / 60))

    @staticmethod
    def _calculate_gross_pnl(lay_stake: Decimal, lay_odds: Decimal, back_odds: Decimal) -> Decimal:
        """Green-up P&L: lay_stake × (back_odds − lay_odds) / back_odds."""
        if back_odds == Decimal("0"):
            return Decimal("0")
        return lay_stake * (back_odds - lay_odds) / back_odds
