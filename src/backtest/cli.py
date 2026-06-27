"""CLI entry point for the LTD backtester.

Usage::

    python -m src.backtest.cli --file data/1.12345.bz2
    python -m src.backtest.cli --dir data/ --output report.csv
    python -m src.backtest.cli --dir data/ --config config/settings.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.backtest.loader import HistoricalLoader
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
    parser.add_argument("--output", type=Path, default=None, metavar="CSV", help="CSV output path")
    parser.add_argument("--config", type=Path, default=None, metavar="YAML", help="settings.yaml path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Run the backtester against one file or a directory and print the report."""
    args = _parse_args(argv)

    try:
        config = load_config(args.config)
        secrets = load_secrets()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(config.logging)
    logger = logging.getLogger(__name__)

    loader = HistoricalLoader()
    if args.file:
        market_list = [m for m in [loader.load_file(args.file)] if m is not None]
    else:
        market_list = list(loader.load_directory(args.dir))

    if not market_list:
        logger.error("No valid market data found — check file paths")
        sys.exit(1)

    session = get_session(secrets.database_url)
    repository = Repository(session)
    try:
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
