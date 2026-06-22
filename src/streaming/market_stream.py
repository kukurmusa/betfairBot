"""Flumine strategy — market discovery, tick persistence, and heartbeat logging.

Flumine manages the streaming connection, reconnection, and heartbeats.
This class handles draw-runner identification, Postgres writes, and
optional dispatch to LTDStrategy.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from flumine.strategy.strategy import BaseStrategy

from src.db.repository import Repository
from src.strategy.ltd_strategy import LTDStrategy

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 60.0  # seconds between status log lines


@dataclass
class _StreamContext:
    """Cached state for a tracked market."""

    market_id: str
    db_market_id: uuid.UUID
    event_name: str
    draw_selection_id: int
    kick_off: datetime | None = None
    last_draw_lay_price: Decimal | None = None
    last_draw_back_price: Decimal | None = None
    last_volume: int = 0
    tick_count: int = 0
    last_logged: float = field(default_factory=time.monotonic)


class MarketStream(BaseStrategy):
    """Flumine strategy for LTD data logging and execution.

    Pass ``strategy=None`` for Phase 1 (data logger only).
    Pass a ``LTDStrategy`` instance for Phase 3+ (paper/live trading).
    """

    def __init__(
        self,
        repository: Repository,
        run_id: uuid.UUID,
        strategy: LTDStrategy | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._repository = repository
        self._run_id = run_id
        self._strategy = strategy
        self._markets: dict[str, _StreamContext] = {}

    # ------------------------------------------------------------------
    # Flumine callback — called on every streaming update
    # ------------------------------------------------------------------

    def process_market_book(self, market, market_book) -> None:
        """Discover markets, persist ticks, and optionally dispatch to strategy."""
        market_id = market_book.market_id

        if market_id not in self._markets:
            self._discover_market(market, market_book)
            if market_id not in self._markets:
                return

        ctx = self._markets[market_id]
        draw_lay, draw_back = self._extract_draw_prices(market_book, ctx.draw_selection_id)
        volume = int(market_book.total_matched or 0)

        if draw_lay is not None and draw_back is not None:
            self._repository.insert_tick(
                market_id=ctx.db_market_id,
                draw_lay_price=draw_lay,
                draw_back_price=draw_back,
                volume_matched=volume,
            )
            ctx.tick_count += 1
            ctx.last_draw_lay_price = draw_lay
            ctx.last_draw_back_price = draw_back
            ctx.last_volume = volume

            if self._strategy is not None:
                self._strategy.on_market_book(
                    market_id=ctx.market_id,
                    db_market_id=ctx.db_market_id,
                    betfair_market_id=ctx.market_id,
                    event_name=ctx.event_name,
                    draw_selection_id=ctx.draw_selection_id,
                    draw_lay_price=draw_lay,
                    draw_back_price=draw_back,
                    volume=volume,
                    timestamp=datetime.now(UTC),
                    kick_off=ctx.kick_off,
                )

        self._maybe_log(ctx)

    # ------------------------------------------------------------------
    # Market discovery
    # ------------------------------------------------------------------

    def _discover_market(self, market, market_book) -> None:
        """Identify the draw runner via catalogue; persist market row to DB."""
        catalogue = market.market_catalogue
        if catalogue is None:
            return

        draw_selection_id = self._find_draw_selection_id(catalogue)
        if draw_selection_id is None:
            logger.warning("Market %s has no 'The Draw' runner — skipping", market_book.market_id)
            return

        event_name = catalogue.event.name if catalogue.event else market_book.market_id
        kick_off: datetime | None = getattr(catalogue, "market_start_time", None)

        db_market = self._repository.upsert_market(
            run_id=self._run_id,
            betfair_market_id=market_book.market_id,
            event_name=event_name,
            market_type="MATCH_ODDS",
            kick_off=kick_off,
            status="pending",
        )

        self._markets[market_book.market_id] = _StreamContext(
            market_id=market_book.market_id,
            db_market_id=db_market.id,
            event_name=event_name,
            draw_selection_id=draw_selection_id,
            kick_off=kick_off,
        )
        logger.info("Tracking: %s", event_name)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_draw_selection_id(catalogue) -> int | None:
        """Return the selection_id of 'The Draw' runner from catalogue data."""
        runners = getattr(catalogue, "runners", None)
        if not runners:
            return None
        for runner in runners:
            if getattr(runner, "runner_name", None) == "The Draw":
                return runner.selection_id
        return None

    @staticmethod
    def _extract_draw_prices(
        market_book, draw_selection_id: int
    ) -> tuple[Decimal | None, Decimal | None]:
        """Extract best lay and back prices for the draw runner."""
        for runner in market_book.runners:
            if runner.selection_id == draw_selection_id:
                ex = runner.ex
                if not ex:
                    return None, None
                lay = Decimal(str(ex.available_to_lay[0].price)) if ex.available_to_lay else None
                back = Decimal(str(ex.available_to_back[0].price)) if ex.available_to_back else None
                return lay, back
        return None, None

    def _maybe_log(self, ctx: _StreamContext) -> None:
        """Log market status every 60 seconds (heartbeat)."""
        now = time.monotonic()
        if now - ctx.last_logged < _HEARTBEAT_INTERVAL:
            return
        logger.info(
            "%s | Draw Lay: %.2f | Ticks: %d",
            ctx.event_name,
            ctx.last_draw_lay_price or Decimal("0"),
            ctx.tick_count,
        )
        ctx.last_logged = now
