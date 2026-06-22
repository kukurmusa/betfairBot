"""Unit tests for main() — patches all external I/O."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.exceptions import BetfairAuthError
from src.config.settings import ConfigError


def _mock_run():
    run = MagicMock()
    run.id = uuid.uuid4()
    return run


# ---------------------------------------------------------------------------
# Config errors
# ---------------------------------------------------------------------------


def test_config_error_exits_1() -> None:
    from src.main import main
    with patch("src.main.load_config", side_effect=ConfigError("missing field")), \
         patch("src.main.load_secrets", MagicMock()), \
         patch("src.main.setup_logging", MagicMock()):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1


def test_secrets_error_exits_1() -> None:
    from src.main import main
    with patch("src.main.load_config", MagicMock(return_value=MagicMock())), \
         patch("src.main.load_secrets", side_effect=ConfigError("missing BETFAIR_APP_KEY")):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Auth failure
# ---------------------------------------------------------------------------


def test_auth_failure_exits_1() -> None:
    mock_run = _mock_run()
    mock_repo_instance = MagicMock()
    mock_repo_instance.create_run.return_value = mock_run

    mock_auth_cls = MagicMock()
    mock_auth_cls.return_value.login.side_effect = BetfairAuthError("Invalid credentials")

    from src.main import main
    with patch("src.main.load_config", MagicMock(return_value=MagicMock())), \
         patch("src.main.load_secrets", MagicMock(return_value=MagicMock(database_url="postgresql+psycopg2://x"))), \
         patch("src.main.setup_logging", MagicMock()), \
         patch("src.main.get_session", MagicMock(return_value=MagicMock())), \
         patch("src.main.dispose_engine", MagicMock()), \
         patch("src.main.Repository", MagicMock(return_value=mock_repo_instance)), \
         patch("src.main.BetfairAuth", mock_auth_cls):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# KeyboardInterrupt — graceful shutdown
# ---------------------------------------------------------------------------


def test_keyboard_interrupt_shuts_down_cleanly() -> None:
    mock_run = _mock_run()
    mock_repo_instance = MagicMock()
    mock_repo_instance.create_run.return_value = mock_run

    mock_session = MagicMock()
    mock_auth_instance = MagicMock()
    mock_auth_instance.login.return_value = MagicMock()
    mock_auth_instance.get_competition_ids.return_value = {"Premier League": "10932509"}

    mock_flumine_instance = MagicMock()
    mock_flumine_instance.run.side_effect = KeyboardInterrupt
    mock_dispose = MagicMock()

    from src.main import main
    with patch("src.main.load_config", MagicMock(return_value=MagicMock())), \
         patch("src.main.load_secrets", MagicMock(return_value=MagicMock(database_url="postgresql+psycopg2://x"))), \
         patch("src.main.setup_logging", MagicMock()), \
         patch("src.main.get_session", MagicMock(return_value=mock_session)), \
         patch("src.main.dispose_engine", mock_dispose), \
         patch("src.main.Repository", MagicMock(return_value=mock_repo_instance)), \
         patch("src.main.BetfairAuth", MagicMock(return_value=mock_auth_instance)), \
         patch("src.main.Flumine", MagicMock(return_value=mock_flumine_instance)), \
         patch("src.main.clients", MagicMock()), \
         patch("src.main.MarketStream", MagicMock()), \
         patch("src.main.streaming_market_filter", MagicMock(return_value=MagicMock())), \
         patch("src.main.streaming_market_data_filter", MagicMock(return_value=MagicMock())):
        main()  # should NOT raise

    mock_repo_instance.end_run.assert_called_once_with(mock_run.id)
    mock_session.close.assert_called_once()
    mock_dispose.assert_called_once()


# ---------------------------------------------------------------------------
# Flumine runtime error — still shuts down cleanly
# ---------------------------------------------------------------------------


def test_flumine_error_shuts_down_cleanly() -> None:
    mock_run = _mock_run()
    mock_repo_instance = MagicMock()
    mock_repo_instance.create_run.return_value = mock_run

    mock_session = MagicMock()
    mock_auth_instance = MagicMock()
    mock_auth_instance.login.return_value = MagicMock()
    mock_auth_instance.get_competition_ids.return_value = {}

    mock_flumine_instance = MagicMock()
    mock_flumine_instance.run.side_effect = RuntimeError("Stream lost")
    mock_dispose = MagicMock()

    from src.main import main
    with patch("src.main.load_config", MagicMock(return_value=MagicMock())), \
         patch("src.main.load_secrets", MagicMock(return_value=MagicMock(database_url="postgresql+psycopg2://x"))), \
         patch("src.main.setup_logging", MagicMock()), \
         patch("src.main.get_session", MagicMock(return_value=mock_session)), \
         patch("src.main.dispose_engine", mock_dispose), \
         patch("src.main.Repository", MagicMock(return_value=mock_repo_instance)), \
         patch("src.main.BetfairAuth", MagicMock(return_value=mock_auth_instance)), \
         patch("src.main.Flumine", MagicMock(return_value=mock_flumine_instance)), \
         patch("src.main.clients", MagicMock()), \
         patch("src.main.MarketStream", MagicMock()), \
         patch("src.main.streaming_market_filter", MagicMock(return_value=MagicMock())), \
         patch("src.main.streaming_market_data_filter", MagicMock(return_value=MagicMock())):
        main()  # should NOT raise

    mock_repo_instance.end_run.assert_called_once_with(mock_run.id)
    mock_session.close.assert_called_once()
    mock_dispose.assert_called_once()


# ---------------------------------------------------------------------------
# Happy path — flumine wired correctly
# ---------------------------------------------------------------------------


def test_happy_path_adds_strategy_and_runs() -> None:
    mock_run = _mock_run()
    mock_repo_instance = MagicMock()
    mock_repo_instance.create_run.return_value = mock_run

    mock_auth_instance = MagicMock()
    mock_auth_instance.login.return_value = MagicMock()
    mock_auth_instance.get_competition_ids.return_value = {"Premier League": "10932509"}

    mock_flumine_instance = MagicMock()
    mock_stream = MagicMock()
    mock_stream_cls = MagicMock(return_value=mock_stream)

    from src.main import main
    with patch("src.main.load_config", MagicMock(return_value=MagicMock())), \
         patch("src.main.load_secrets", MagicMock(return_value=MagicMock(database_url="postgresql+psycopg2://x"))), \
         patch("src.main.setup_logging", MagicMock()), \
         patch("src.main.get_session", MagicMock(return_value=MagicMock())), \
         patch("src.main.dispose_engine", MagicMock()), \
         patch("src.main.Repository", MagicMock(return_value=mock_repo_instance)), \
         patch("src.main.BetfairAuth", MagicMock(return_value=mock_auth_instance)), \
         patch("src.main.Flumine", MagicMock(return_value=mock_flumine_instance)), \
         patch("src.main.clients", MagicMock()), \
         patch("src.main.MarketStream", mock_stream_cls), \
         patch("src.main.streaming_market_filter", MagicMock(return_value=MagicMock())), \
         patch("src.main.streaming_market_data_filter", MagicMock(return_value=MagicMock())):
        main()

    mock_flumine_instance.add_strategy.assert_called_once_with(mock_stream)
    mock_flumine_instance.run.assert_called_once()
    # Phase 1: strategy=None wired in
    mock_stream_cls.assert_called_once()
    call_kwargs = mock_stream_cls.call_args.kwargs
    assert call_kwargs.get("strategy") is None
    assert call_kwargs.get("run_id") == mock_run.id
