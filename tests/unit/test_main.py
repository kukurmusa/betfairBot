"""Unit tests for main.py — control flow with mocked dependencies."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.exceptions import BetfairAuthError, BetfairStreamError


# ---------------------------------------------------------------------------
# Helper: build a mock session factory that yields an AsyncMock session
# ---------------------------------------------------------------------------

def _mock_session_factory() -> MagicMock:
    """Return a mock session factory whose context manager yields an AsyncMock."""
    mock_session = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = mock_session
    return factory


# ---------------------------------------------------------------------------
# Auth failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_auth_failure() -> None:
    """Auth failure should exit with code 1 after ending the run."""
    mock_repo = MagicMock()
    mock_repo.create_run = AsyncMock(return_value=MagicMock())
    mock_repo.end_run = AsyncMock()

    with (
        patch("src.main.load_config") as mock_load_cfg,
        patch("src.main.load_secrets") as mock_load_sec,
        patch("src.main.setup_logging"),
        patch("src.main.create_session_factory", return_value=_mock_session_factory()),
        patch("src.main.Repository", return_value=mock_repo),
        patch("src.main.BetfairAuth") as mock_auth_cls,
    ):
        mock_load_cfg.return_value = MagicMock()
        mock_load_cfg.return_value.logging.level = "INFO"
        mock_load_sec.return_value = MagicMock()

        mock_auth = mock_auth_cls.return_value
        mock_auth.login.side_effect = BetfairAuthError("Bad cert")

        from src.main import main

        with pytest.raises(SystemExit) as exc_info:
            await main()

        assert exc_info.value.code == 1
        mock_repo.end_run.assert_called_once()


# ---------------------------------------------------------------------------
# Streaming failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_streaming_failure() -> None:
    """Streaming failure should trigger graceful shutdown."""
    mock_repo = MagicMock()
    mock_repo.create_run = AsyncMock(return_value=MagicMock())
    mock_repo.end_run = AsyncMock()

    mock_stream = MagicMock()
    mock_stream.run = AsyncMock(side_effect=BetfairStreamError("Connection lost"))
    mock_stream.stop = AsyncMock()

    with (
        patch("src.main.load_config") as mock_load_cfg,
        patch("src.main.load_secrets") as mock_load_sec,
        patch("src.main.setup_logging"),
        patch("src.main.create_session_factory", return_value=_mock_session_factory()),
        patch("src.main.Repository", return_value=mock_repo),
        patch("src.main.BetfairAuth") as mock_auth_cls,
        patch("src.main.GoalDetector") as mock_gd_cls,
        patch("src.main.LTDStrategy") as mock_strat_cls,
        patch("src.main.MarketStream", return_value=mock_stream),
    ):
        mock_load_cfg.return_value = MagicMock()
        mock_load_cfg.return_value.logging.level = "INFO"
        mock_load_sec.return_value = MagicMock()

        mock_auth = mock_auth_cls.return_value
        mock_auth.login = AsyncMock(return_value=MagicMock())
        mock_auth.get_competition_ids = AsyncMock(return_value={})

        from src.main import main

        await main()

        mock_repo.end_run.assert_called_once()


# ---------------------------------------------------------------------------
# Keyboard interrupt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_keyboard_interrupt() -> None:
    """Ctrl+C should trigger clean shutdown with end_run."""
    mock_repo = MagicMock()
    mock_repo.create_run = AsyncMock(return_value=MagicMock())
    mock_repo.end_run = AsyncMock()

    mock_stream = MagicMock()
    mock_stream.run = AsyncMock(side_effect=KeyboardInterrupt())
    mock_stream.stop = AsyncMock()

    with (
        patch("src.main.load_config") as mock_load_cfg,
        patch("src.main.load_secrets") as mock_load_sec,
        patch("src.main.setup_logging"),
        patch("src.main.create_session_factory", return_value=_mock_session_factory()),
        patch("src.main.Repository", return_value=mock_repo),
        patch("src.main.BetfairAuth") as mock_auth_cls,
        patch("src.main.GoalDetector") as mock_gd_cls,
        patch("src.main.LTDStrategy") as mock_strat_cls,
        patch("src.main.MarketStream", return_value=mock_stream),
    ):
        mock_load_cfg.return_value = MagicMock()
        mock_load_cfg.return_value.logging.level = "INFO"
        mock_load_sec.return_value = MagicMock()

        mock_auth = mock_auth_cls.return_value
        mock_auth.login = AsyncMock(return_value=MagicMock())
        mock_auth.get_competition_ids = AsyncMock(return_value={})

        from src.main import main

        await main()

        mock_repo.end_run.assert_called_once()


# ---------------------------------------------------------------------------
# Config failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_config_failure() -> None:
    """Config error should exit with code 1 before any DB or API calls."""
    with (
        patch("src.main.load_config", side_effect=SystemExit(1)),
        patch("src.main.load_secrets"),
        patch("src.main.setup_logging"),
        patch("src.main.create_session_factory") as mock_session_factory,
        patch("src.main.Repository") as mock_repo_cls,
        patch("src.main.BetfairAuth") as mock_auth_cls,
    ):
        from src.main import main

        with pytest.raises(SystemExit) as exc_info:
            await main()

        assert exc_info.value.code == 1
        # Should NOT have called DB or Auth
        mock_session_factory.assert_not_called()
