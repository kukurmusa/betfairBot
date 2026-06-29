"""Entry point for the Betfair LTD trading bot.

Usage::

    python -m src.main
"""

from __future__ import annotations

import logging
import sys

from betfairlightweight.filters import streaming_market_data_filter, streaming_market_filter
from flumine import Flumine, clients

from src.auth.betfair_auth import BetfairAuth
from src.config.settings import ConfigError, load_config, load_secrets
from src.db.repository import Repository
from src.db.session import dispose_engine, get_session
from src.exceptions import BetfairAuthError
from src.goal_detection.detector import GoalDetector
from src.logging_config import setup_logging
from src.risk.risk_manager import RiskManager
from src.strategy.ltd_strategy import LTDStrategy
from src.streaming.market_stream import MarketStream

logger = logging.getLogger(__name__)


def main() -> None:
    """Application entry point. Exits with code 1 on fatal errors."""

    # 1. Config (fail fast before any I/O)
    try:
        config = load_config()
        secrets = load_secrets()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(config.logging)

    # 2. Database
    session = get_session(secrets.database_url)
    repository = Repository(session)
    run_mode = "paper" if config.paper_mode else "live"
    run = repository.create_run(mode=run_mode, strategy_name="ltd_v1")

    try:
        # 3. Auth
        try:
            auth = BetfairAuth(secrets)
            trading_client = auth.login()
        except BetfairAuthError as exc:
            logger.critical("Authentication failed: %s", exc)
            sys.exit(1)

        # 4. Resolve competition IDs for logging — the Betfair streaming API does not
        #    support competition_id filtering at subscription level, so we log what we
        #    found and rely on entry criteria (odds, volume) to filter irrelevant markets.
        try:
            competition_ids = auth.get_competition_ids(config.streaming.target_competitions)
            if competition_ids:
                logger.info("Tracking %d competition(s): %s", len(competition_ids), list(competition_ids.keys()))
        except BetfairAuthError as exc:
            logger.warning("Competition resolution failed: %s", exc)

        # 5. Build market filter — event type 1 = football, MATCH_ODDS only
        market_filter = streaming_market_filter(
            event_type_ids=["1"],
            market_types=["MATCH_ODDS"],
        )
        data_filter = streaming_market_data_filter(
            fields=["EX_BEST_OFFERS", "EX_MARKET_DEF"],
            ladder_levels=3,
        )

        # 6. Strategy stack
        risk_manager = RiskManager(config.strategy)
        goal_detector = GoalDetector(config.strategy.goal_spike_threshold)
        ltd_strategy = LTDStrategy(
            config=config.strategy,
            risk_manager=risk_manager,
            goal_detector=goal_detector,
            repository=repository,
            run_id=run.id,
        )

        stream = MarketStream(
            market_filter=market_filter,
            market_data_filter=data_filter,
            repository=repository,
            run_id=run.id,
            strategy=ltd_strategy,
        )

        # 7. Flumine handles connection, reconnection, and heartbeats
        client = clients.BetfairClient(trading_client)
        framework = Flumine(client=client)
        framework.add_strategy(stream)

        logger.info("Bot started (run_id=%s, mode=%s)", run.id, run_mode)
        try:
            framework.run()
        except Exception as exc:
            logger.critical("Fatal streaming error: %s", exc)

    except KeyboardInterrupt:
        logger.info("Shutdown requested (Ctrl+C)")
    finally:
        logger.info("Shutting down...")
        repository.end_run(run.id)
        session.close()
        dispose_engine()
        logger.info("Bot shutdown complete.")


if __name__ == "__main__":
    main()
