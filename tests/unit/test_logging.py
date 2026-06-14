"""Unit tests for logging configuration."""

from __future__ import annotations

import logging

from src.config.settings import LoggingConfig
from src.logging_config import setup_logging


def test_setup_logging_info() -> None:
    """setup_logging with INFO should set root logger level to INFO."""
    setup_logging(LoggingConfig(level="INFO"))
    assert logging.getLogger().level == logging.INFO


def test_setup_logging_debug() -> None:
    """setup_logging with DEBUG should set root logger level to DEBUG."""
    setup_logging(LoggingConfig(level="DEBUG"))
    assert logging.getLogger().level == logging.DEBUG


def test_setup_logging_case_insensitive() -> None:
    """Level names should work regardless of case."""
    setup_logging(LoggingConfig(level="info"))
    assert logging.getLogger().level == logging.INFO


def test_setup_logging_default() -> None:
    """Default LoggingConfig should be INFO."""
    cfg = LoggingConfig()
    assert cfg.level == "INFO"
