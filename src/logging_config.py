"""Application-wide logging configuration.

Configures the root logger with a structured plain-text format.
Switch to JSON logging (structlog) in Phase 4+ when log aggregation matters.
"""

from __future__ import annotations

import logging
import sys

from src.config.settings import LoggingConfig


def setup_logging(config: LoggingConfig) -> None:
    """Configure application-wide logging.

    Format: ``2026-06-14T14:30:00+0000 [INFO] src.mod: message``

    Args:
        config: Validated logging configuration.
    """
    logging.basicConfig(
        level=logging.getLevelName(config.level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        stream=sys.stdout,
        force=True,
    )
