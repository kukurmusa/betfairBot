"""Unit tests for BetfairAuth — all external calls are mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.auth.betfair_auth import BetfairAuth
from src.config.settings import SecretsConfig
from src.exceptions import BetfairAuthError


def _make_secrets() -> SecretsConfig:
    return SecretsConfig(
        betfair_app_key="test-app-key",
        betfair_username="test_user",
        betfair_cert_path=__file__,
        betfair_cert_key_path=__file__,
        database_url="postgresql+psycopg2://localhost/test",
    )


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
def test_login_success(mock_client_class: MagicMock) -> None:
    mock_client = mock_client_class.return_value
    auth = BetfairAuth(_make_secrets())
    client = auth.login()
    assert client is mock_client
    mock_client.login.assert_called_once()


@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
def test_login_failure(mock_client_class: MagicMock) -> None:
    mock_client_class.return_value.login.side_effect = Exception("Invalid credentials")
    auth = BetfairAuth(_make_secrets())
    with pytest.raises(BetfairAuthError, match="login failed"):
        auth.login()


# ---------------------------------------------------------------------------
# session_token
# ---------------------------------------------------------------------------


@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
def test_session_token_after_login(mock_client_class: MagicMock) -> None:
    mock_client = mock_client_class.return_value
    mock_client.session_token = "abc123-session-token"
    auth = BetfairAuth(_make_secrets())
    auth.login()
    assert auth.session_token == "abc123-session-token"


def test_session_token_before_login() -> None:
    auth = BetfairAuth(_make_secrets())
    assert auth.session_token is None


# ---------------------------------------------------------------------------
# get_competition_ids
# ---------------------------------------------------------------------------


class _FakeCompetition:
    def __init__(self, name: str, comp_id: str) -> None:
        self.competition = type("obj", (), {"name": name, "id": comp_id})()


@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
def test_get_competition_ids_success(mock_client_class: MagicMock) -> None:
    mock_client = mock_client_class.return_value
    mock_client.list_competitions.return_value = [
        _FakeCompetition("Premier League", "10932509"),
        _FakeCompetition("Championship", "7129730"),
        _FakeCompetition("La Liga", "117"),
    ]
    auth = BetfairAuth(_make_secrets())
    auth.login()
    result = auth.get_competition_ids(["Premier League", "Championship"])
    assert result == {"Premier League": "10932509", "Championship": "7129730"}


@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
def test_get_competition_ids_partial_match(mock_client_class: MagicMock) -> None:
    mock_client = mock_client_class.return_value
    mock_client.list_competitions.return_value = [_FakeCompetition("Premier League", "10932509")]
    auth = BetfairAuth(_make_secrets())
    auth.login()
    result = auth.get_competition_ids(["Premier League", "Serie A"])
    assert result == {"Premier League": "10932509"}


@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
def test_get_competition_ids_no_match(mock_client_class: MagicMock) -> None:
    mock_client = mock_client_class.return_value
    mock_client.list_competitions.return_value = []
    auth = BetfairAuth(_make_secrets())
    auth.login()
    assert auth.get_competition_ids(["Premier League"]) == {}


def test_get_competition_ids_before_login() -> None:
    auth = BetfairAuth(_make_secrets())
    with pytest.raises(BetfairAuthError, match="Not authenticated"):
        auth.get_competition_ids(["Premier League"])
