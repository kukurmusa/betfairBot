"""Entry point for the Betfair LTD trading bot.

Orchestrates config loading, database setup, Betfair authentication,
and the streaming data pipeline.

Usage::

    python -m src.main
"""

from __future__ import annotations

import asyncio
import logging
import sys

from src.auth.betfair_auth import BetfairAuth
from src.config.settings import ConfigError, load_config, load_secrets
from src.db.repository import Repository
from src.db.session import create_session_factory, dispose_engine
from src.exceptions import BetfairAuthError, BetfairStreamError
from src.goal_detection.detector import GoalDetector
from src.logging_config import setup_logging
from src.risk.risk_manager import RiskManager
from src.strategy.ltd_strategy import LTDStrategy
from src.streaming.market_stream import MarketStream

logger = logging.getLogger(__name__)


async def main() -> None:
    """Application entry point.  Exits with code 1 on fatal errors."""

    # 1. Load and validate config / secrets (fail fast)
    try:
        config = load_config()
        secrets = load_secrets()
    except ConfigError as exc:
        # Logging not configured yet — print to stderr
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    # 2. Configure logging
    setup_logging(config.logging)

    # 3. Database
    session_factory = create_session_factory(secrets.database_url)

    async with session_factory() as session:
        repository = Repository(session)

        # 4. Create run record
        run = await repository.create_run(
            mode="paper",
            strategy_name="ltd_v1",
        )

        try:
            # 5. Betfair authentication
            try:
                auth = BetfairAuth(secrets)
                trading_client = await auth.login()
            except BetfairAuthError as exc:
                logger.critical("Authentication failed: %s", exc)
                sys.exit(1)  # finally block handles end_run

            # 6. Resolve competition IDs
            competition_ids: dict[str, str] = {}
            try:
                competition_ids = await auth.get_competition_ids(
                    config.streaming.target_competitions
                )
            except BetfairAuthError as exc:
                logger.warning(
                    "Competition resolution failed: %s. "
                    "Stream will proceed without competition filter.",
                    exc,
                )

            if not competition_ids:
                logger.warning(
                    "No target competitions resolved. "
                    "Stream will receive no market data until competitions "
                    "become available."
                )

            # 7. Components
            risk_manager = RiskManager(config.strategy)
            goal_detector = GoalDetector(config.strategy.goal_spike_threshold)
            strategy = LTDStrategy(
                config=config.strategy,
                risk_manager=risk_manager,
                goal_detector=goal_detector,
                repository=repository,
                run_id=run.id,
            )

            # 8. Start streaming
            stream = MarketStream(
                trading_client=trading_client,
                competition_ids=competition_ids,
                config=config.streaming,
                secrets=secrets,
                repository=repository,
                run_id=run.id,
                strategy=strategy,
            )

            logger.info(
                "Bot started (run_id=%s, mode=%s, strategy=%s)",
                run.id,
                run.mode,
                run.strategy_name,
            )

            try:
                await stream.run()
            except BetfairStreamError as exc:
                logger.critical("Streaming error: %s", exc)

        except KeyboardInterrupt:
            logger.info("Shutdown requested (Ctrl+C)")
        finally:
            logger.info("Shutting down...")
            await repository.end_run(run.id)
            logger.info("Bot shutdown complete")

    # 9. Clean up database connections
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
