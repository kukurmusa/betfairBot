"""Backtest replay engine.

Feeds parsed historical ticks through LTDStrategy and persists orders
and trades via Repository, all tagged with a single backtest run_id.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

from src.backtest.loader import MarketData
from src.config.settings import StrategyConfig
from src.db.repository import Repository
from src.goal_detection.detector import GoalDetector
from src.risk.risk_manager import RiskManager
from src.strategy.ltd_strategy import LTDStrategy

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplayResult:
    """Outcome of a completed backtest run."""

    run_id: uuid.UUID
    markets_processed: int
    ticks_processed: int


class BacktestReplay:
    """Replay historical tick data through the live strategy logic."""

    def __init__(self, config: StrategyConfig, repository: Repository) -> None:
        """Initialise with strategy config and a DB repository."""
        self._config = config
        self._repository = repository

    def run(self, markets: list[MarketData]) -> ReplayResult:
        """Create a backtest run, replay all markets, and persist results.

        A fresh strategy stack is created per run so state never leaks
        between calls. Markets are replayed sequentially.
        """
        db_run = self._repository.create_run(mode="backtest", strategy_name="ltd_v1")
        risk_manager = RiskManager(self._config)
        goal_detector = GoalDetector(self._config.goal_spike_threshold)
        strategy = LTDStrategy(
            config=self._config,
            risk_manager=risk_manager,
            goal_detector=goal_detector,
            repository=self._repository,
            run_id=db_run.id,
        )

        total_ticks = 0
        for market_data in markets:
            n = self._replay_market(strategy, db_run.id, market_data)
            total_ticks += n
            logger.info("Replayed %s: %d ticks", market_data.event_name, n)

        self._repository.end_run(
            db_run.id, total_pnl=Decimal(str(risk_manager.daily_pnl))
        )
        return ReplayResult(
            run_id=db_run.id,
            markets_processed=len(markets),
            ticks_processed=total_ticks,
        )

    def _replay_market(
        self,
        strategy: LTDStrategy,
        run_id: uuid.UUID,
        market_data: MarketData,
    ) -> int:
        """Upsert the market record then feed all ticks to the strategy."""
        db_market = self._repository.upsert_market(
            run_id=run_id,
            betfair_market_id=market_data.market_id,
            event_name=market_data.event_name,
            market_type="MATCH_ODDS",
            kick_off=market_data.kick_off,
            status="pending",
        )
        for tick in market_data.ticks:
            strategy.on_market_book(
                market_id=market_data.market_id,
                db_market_id=db_market.id,
                betfair_market_id=market_data.market_id,
                event_name=market_data.event_name,
                draw_selection_id=market_data.draw_selection_id,
                draw_lay_price=tick.draw_lay_price,
                draw_back_price=tick.draw_back_price,
                volume=tick.volume,
                timestamp=tick.timestamp,
                kick_off=market_data.kick_off,
            )
        return len(market_data.ticks)
