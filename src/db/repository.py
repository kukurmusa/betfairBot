"""Repository pattern — all database access goes through this module.

No raw SQL or direct session usage elsewhere in the application.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Market, Order, Run, Tick, Trade
from src.exceptions import DatabaseError

logger = logging.getLogger(__name__)


class Repository:
    """Data access layer for the trading database."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def create_run(self, mode: str, strategy_name: str, started_at: datetime | None = None) -> Run:
        """Create a new bot run record."""
        run = Run(
            id=uuid.uuid4(),
            mode=mode,
            strategy_name=strategy_name,
            started_at=started_at or datetime.now(UTC),
        )
        try:
            self._session.add(run)
            self._session.commit()
            logger.info("Created run %s (mode=%s, strategy=%s)", run.id, mode, strategy_name)
            return run
        except Exception as exc:
            self._session.rollback()
            raise DatabaseError(f"Failed to create run: {exc}") from exc

    def end_run(
        self,
        run_id: uuid.UUID,
        total_pnl: Decimal | None = None,
        commission_paid: Decimal | None = None,
    ) -> None:
        """Mark a run as ended."""
        try:
            run = self._session.get(Run, run_id)
            if run is None:
                raise DatabaseError(f"Run not found: {run_id}")
            run.ended_at = datetime.now(UTC)
            if total_pnl is not None:
                run.total_pnl = float(total_pnl)
            if commission_paid is not None:
                run.commission_paid = float(commission_paid)
            self._session.commit()
            logger.info("Ended run %s", run_id)
        except DatabaseError:
            raise
        except Exception as exc:
            self._session.rollback()
            raise DatabaseError(f"Failed to end run {run_id}: {exc}") from exc

    # ------------------------------------------------------------------
    # Markets
    # ------------------------------------------------------------------

    def upsert_market(
        self,
        run_id: uuid.UUID,
        betfair_market_id: str,
        event_name: str,
        market_type: str = "MATCH_ODDS",
        kick_off: datetime | None = None,
        status: str = "pending",
    ) -> Market:
        """Insert a new market or return the existing one."""
        try:
            existing = self.get_market_by_betfair_id(betfair_market_id)
            if existing is not None:
                return existing
            market = Market(
                id=uuid.uuid4(),
                run_id=run_id,
                betfair_market_id=betfair_market_id,
                event_name=event_name,
                market_type=market_type,
                kick_off=kick_off,
                status=status,
            )
            self._session.add(market)
            self._session.commit()
            logger.info("New market: %s (%s)", event_name, betfair_market_id)
            return market
        except DatabaseError:
            raise
        except Exception as exc:
            self._session.rollback()
            raise DatabaseError(f"Failed to upsert market {betfair_market_id}: {exc}") from exc

    def get_market_by_betfair_id(self, betfair_market_id: str) -> Market | None:
        """Look up a market by its Betfair market ID."""
        stmt = select(Market).where(Market.betfair_market_id == betfair_market_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_active_markets(self) -> Sequence[Market]:
        """Return all markets currently in ``pending`` or ``active`` status."""
        stmt = select(Market).where(Market.status.in_(["pending", "active"]))
        return self._session.execute(stmt).scalars().all()

    # ------------------------------------------------------------------
    # Ticks
    # ------------------------------------------------------------------

    def insert_tick(
        self,
        market_id: uuid.UUID,
        draw_lay_price: Decimal,
        draw_back_price: Decimal,
        volume_matched: int,
    ) -> Tick:
        """Insert a price snapshot for the draw runner."""
        try:
            tick = Tick(
                id=uuid.uuid4(),
                market_id=market_id,
                draw_lay_price=float(draw_lay_price),
                draw_back_price=float(draw_back_price),
                volume_matched=volume_matched,
                recorded_at=datetime.now(UTC),
            )
            self._session.add(tick)
            self._session.commit()
            return tick
        except Exception as exc:
            self._session.rollback()
            raise DatabaseError(f"Failed to insert tick for market {market_id}: {exc}") from exc

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def insert_order(
        self,
        market_id: uuid.UUID,
        run_id: uuid.UUID,
        side: str,
        price: Decimal,
        size: Decimal,
        status: str = "pending",
        betfair_bet_id: str | None = None,
    ) -> Order:
        """Create an order row."""
        try:
            order = Order(
                id=uuid.uuid4(),
                market_id=market_id,
                run_id=run_id,
                side=side,
                price=float(price),
                size=float(size),
                status=status,
                betfair_bet_id=betfair_bet_id,
                placed_at=datetime.now(UTC),
                matched_at=datetime.now(UTC) if status == "matched" else None,
            )
            self._session.add(order)
            self._session.commit()
            logger.info("Order: %s %s @ %.2f size=%.4f (id=%s)", side, market_id, price, size, order.id)
            return order
        except Exception as exc:
            self._session.rollback()
            raise DatabaseError(f"Failed to insert order for market {market_id}: {exc}") from exc

    def update_order_status(
        self,
        order_id: uuid.UUID,
        status: str,
        betfair_bet_id: str | None = None,
        matched_at: datetime | None = None,
    ) -> None:
        """Update an order's status after fill or cancellation."""
        try:
            order = self._session.get(Order, order_id)
            if order is None:
                raise DatabaseError(f"Order not found: {order_id}")
            order.status = status
            if betfair_bet_id is not None:
                order.betfair_bet_id = betfair_bet_id
            if status == "matched" and order.matched_at is None:
                order.matched_at = matched_at or datetime.now(UTC)
            self._session.commit()
        except DatabaseError:
            raise
        except Exception as exc:
            self._session.rollback()
            raise DatabaseError(f"Failed to update order {order_id}: {exc}") from exc

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def insert_trade(
        self,
        market_id: uuid.UUID,
        run_id: uuid.UUID,
        entry_order_id: uuid.UUID,
        entry_price: Decimal,
        stake: Decimal,
        exit_order_id: uuid.UUID | None = None,
        exit_price: Decimal | None = None,
        gross_pnl: Decimal | None = None,
        commission: Decimal | None = None,
        net_pnl: Decimal | None = None,
        exit_reason: str | None = None,
    ) -> Trade:
        """Create a completed trade row."""
        try:
            trade = Trade(
                id=uuid.uuid4(),
                market_id=market_id,
                run_id=run_id,
                entry_order_id=entry_order_id,
                exit_order_id=exit_order_id,
                entry_price=float(entry_price),
                exit_price=float(exit_price) if exit_price is not None else None,
                stake=float(stake),
                gross_pnl=float(gross_pnl) if gross_pnl is not None else None,
                commission=float(commission) if commission is not None else None,
                net_pnl=float(net_pnl) if net_pnl is not None else None,
                exit_reason=exit_reason,
                opened_at=datetime.now(UTC),
                closed_at=datetime.now(UTC) if exit_order_id is not None else None,
            )
            self._session.add(trade)
            self._session.commit()
            logger.info("Trade: market=%s net_pnl=%.2f reason=%s (id=%s)", market_id, net_pnl or 0, exit_reason, trade.id)
            return trade
        except Exception as exc:
            self._session.rollback()
            raise DatabaseError(f"Failed to insert trade for market {market_id}: {exc}") from exc

    def get_trades_for_run(self, run_id: uuid.UUID) -> Sequence[Trade]:
        """Return all trades for a run ordered by opened_at."""
        try:
            stmt = select(Trade).where(Trade.run_id == run_id).order_by(Trade.opened_at)
            return self._session.execute(stmt).scalars().all()
        except Exception as exc:
            raise DatabaseError(f"Failed to query trades for run {run_id}: {exc}") from exc

    def get_open_positions(self, run_id: uuid.UUID) -> Sequence[Trade]:
        """Return all trades with no exit order (open positions)."""
        try:
            stmt = select(Trade).where(Trade.run_id == run_id, Trade.exit_order_id.is_(None))
            return self._session.execute(stmt).scalars().all()
        except Exception as exc:
            raise DatabaseError(f"Failed to query open positions for run {run_id}: {exc}") from exc
