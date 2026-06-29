"""CLI entry point for the LTD backtester.

Three data sources are supported:

    # Single .bz2 file from Betfair historical data
    python -m src.backtest.cli --file data/1.123456.bz2

    # Directory of .bz2 files
    python -m src.backtest.cli --dir data/ --output report.csv

    # Tick data recorded during a previous paper/live run
    python -m src.backtest.cli --db-run <run-uuid> --output report.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from pathlib import Path

from src.backtest.db_loader import DbLoader
from src.backtest.loader import HistoricalLoader, MarketData
from src.backtest.replay import BacktestReplay
from src.backtest.report import BacktestReport
from src.config.settings import ConfigError, load_config, load_secrets
from src.db.repository import Repository
from src.db.session import dispose_engine, get_session
from src.logging_config import setup_logging


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Betfair LTD backtester")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=Path, metavar="FILE", help="Single .bz2 market file")
    group.add_argument("--dir", type=Path, metavar="DIR", help="Directory of .bz2 files")
    group.add_argument(
        "--db-run", type=uuid.UUID, metavar="RUN_ID",
        help="UUID of a recorded paper/live run to replay",
    )
    parser.add_argument("--output", type=Path, default=None, metavar="CSV", help="CSV output path")
    parser.add_argument("--config", type=Path, default=None, metavar="YAML", help="settings.yaml path")
    return parser.parse_args(argv)


def _load_markets(
    args: argparse.Namespace,
    repository: Repository,
    logger: logging.Logger,
) -> list[MarketData]:
    """Dispatch to the correct loader based on CLI arguments."""
    if args.file:
        result = HistoricalLoader().load_file(args.file)
        return [result] if result is not None else []
    if args.dir:
        return list(HistoricalLoader().load_directory(args.dir))
    # --db-run
    markets = DbLoader(repository).load_run(args.db_run)
    logger.info("Loaded %d markets from DB run %s", len(markets), args.db_run)
    return markets


def main(argv: list[str] | None = None) -> None:
    """Run the backtester against a file, directory, or recorded DB run."""
    args = _parse_args(argv)

    try:
        config = load_config(args.config)
        secrets = load_secrets()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(config.logging)
    logger = logging.getLogger(__name__)

    session = get_session(secrets.database_url)
    repository = Repository(session)
    try:
        market_list = _load_markets(args, repository, logger)
        if not market_list:
            logger.error("No valid market data found — check source arguments")
            sys.exit(1)

        result = BacktestReplay(config.strategy, repository).run(market_list)
        logger.info(
            "Backtest complete: %d markets, %d ticks (run=%s)",
            result.markets_processed, result.ticks_processed, result.run_id,
        )

        report = BacktestReport(repository)
        summary = report.generate(result.run_id)
        report.print_summary(summary)

        if args.output:
            report.to_csv(result.run_id, args.output)

    finally:
        session.close()
        dispose_engine()


if __name__ == "__main__":
    main()
