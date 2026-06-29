"""DB-backed historical loader.

Reads tick data recorded by MarketStream from the ``ticks`` table and
converts it into MarketData objects compatible with BacktestReplay.

This lets you backtest against data you recorded yourself during a
paper or live run — no .bz2 files needed.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from src.backtest.loader import MarketData, MarketTick
from src.db.models import Market
from src.db.repository import Repository

logger = logging.getLogger(__name__)


class DbLoader:
    """Load recorded tick data from the database for replay."""

    def __init__(self, repository: Repository) -> None:
        """Initialise with a DB repository."""
        self._repository = repository

    def load_run(self, run_id: uuid.UUID) -> list[MarketData]:
        """Return MarketData for every market recorded under run_id.

        Markets with no ticks are skipped with a warning.
        """
        markets = self._repository.get_markets_for_run(run_id)
        if not markets:
            logger.warning("No markets found for run %s", run_id)
            return []

        result = [
            md for md in (self._build_market_data(m) for m in markets)
            if md is not None
        ]
        logger.info("Loaded %d markets from run %s", len(result), run_id)
        return result

    def load_market(self, betfair_market_id: str) -> MarketData | None:
        """Return MarketData for a single market by its Betfair market ID.

        Returns None if the market is not in the database or has no ticks.
        """
        market = self._repository.get_market_by_betfair_id(betfair_market_id)
        if market is None:
            logger.warning("Market %s not found in DB", betfair_market_id)
            return None
        return self._build_market_data(market)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _build_market_data(self, market: Market) -> MarketData | None:
        """Convert a Market ORM object and its ticks into MarketData."""
        ticks = self._repository.get_ticks_for_market(market.id)
        if not ticks:
            logger.warning("No ticks for '%s' — skipping", market.event_name)
            return None

        market_ticks = [
            MarketTick(
                timestamp=tick.recorded_at,
                draw_lay_price=Decimal(str(tick.draw_lay_price)),
                draw_back_price=Decimal(str(tick.draw_back_price)),
                volume=tick.volume_matched,
            )
            for tick in ticks
        ]
        logger.info("Loaded '%s': %d ticks", market.event_name, len(market_ticks))
        # draw_selection_id is not stored in ticks; prices are already extracted
        return MarketData(
            market_id=market.betfair_market_id,
            event_name=market.event_name,
            kick_off=market.kick_off,
            draw_selection_id=0,
            ticks=market_ticks,
        )
