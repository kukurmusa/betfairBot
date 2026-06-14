"""Unit tests for BetfairAuth — all external calls are mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.auth.betfair_auth import BetfairAuth
from src.config.settings import SecretsConfig
from src.exceptions import BetfairAuthError


def _make_secrets() -> SecretsConfig:
    """Build a SecretsConfig with placeholder values for tests."""
    return SecretsConfig(
        betfair_app_key="test-app-key",
        betfair_username="test_user",
        betfair_cert_path=__file__,   # exists because this file exists
        betfair_cert_key_path=__file__,
        database_url="postgresql+asyncpg://localhost/test",
    )


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
async def test_login_success(mock_client_class: MagicMock) -> None:
    """On successful login, should return APIClient without error."""
    mock_client = mock_client_class.return_value
    mock_client.login.return_value = None

    auth = BetfairAuth(_make_secrets())
    client = await auth.login()

    assert client is mock_client
    mock_client.login.assert_called_once()


@pytest.mark.asyncio
@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
async def test_login_failure(mock_client_class: MagicMock) -> None:
    """Login failure should raise BetfairAuthError."""
    mock_client = mock_client_class.return_value
    mock_client.login.side_effect = Exception("Invalid credentials")

    auth = BetfairAuth(_make_secrets())

    with pytest.raises(BetfairAuthError, match="login failed"):
        await auth.login()


# ---------------------------------------------------------------------------
# session_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
async def test_session_token_after_login(mock_client_class: MagicMock) -> None:
    """session_token property should return the token from the client."""
    mock_client = mock_client_class.return_value
    mock_client.login.return_value = None
    mock_client.session_token = "abc123-session-token"

    auth = BetfairAuth(_make_secrets())
    await auth.login()

    assert auth.session_token == "abc123-session-token"


def test_session_token_before_login() -> None:
    """session_token should be None before login."""
    auth = BetfairAuth(_make_secrets())
    assert auth.session_token is None


# ---------------------------------------------------------------------------
# get_competition_ids
# ---------------------------------------------------------------------------


class _FakeCompetition:
    """Mock for betfairlightweight competition result."""

    def __init__(self, name: str, comp_id: str) -> None:
        self.competition = type("obj", (), {"name": name, "id": comp_id})()


@pytest.mark.asyncio
@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
async def test_get_competition_ids_success(mock_client_class: MagicMock) -> None:
    """Should return a mapping of found competition names to IDs."""
    mock_client = mock_client_class.return_value
    mock_client.login.return_value = None
    mock_client.list_competitions.return_value = [
        _FakeCompetition("Premier League", "10932509"),
        _FakeCompetition("Championship", "7129730"),
        _FakeCompetition("La Liga", "117"),
    ]

    auth = BetfairAuth(_make_secrets())
    await auth.login()
    result = await auth.get_competition_ids(["Premier League", "Championship"])

    assert result == {
        "Premier League": "10932509",
        "Championship": "7129730",
    }


@pytest.mark.asyncio
@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
async def test_get_competition_ids_partial_match(mock_client_class: MagicMock) -> None:
    """Not-found competitions should be omitted from the result."""
    mock_client = mock_client_class.return_value
    mock_client.login.return_value = None
    mock_client.list_competitions.return_value = [
        _FakeCompetition("Premier League", "10932509"),
    ]

    auth = BetfairAuth(_make_secrets())
    await auth.login()
    result = await auth.get_competition_ids(["Premier League", "Serie A"])

    assert result == {"Premier League": "10932509"}
    assert "Serie A" not in result


@pytest.mark.asyncio
@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
async def test_get_competition_ids_no_match(mock_client_class: MagicMock) -> None:
    """If none match, return empty dict."""
    mock_client = mock_client_class.return_value
    mock_client.login.return_value = None
    mock_client.list_competitions.return_value = []

    auth = BetfairAuth(_make_secrets())
    await auth.login()
    result = await auth.get_competition_ids(["Premier League"])

    assert result == {}


@pytest.mark.asyncio
@patch("src.auth.betfair_auth.betfairlightweight.APIClient")
async def test_get_competition_ids_before_login(mock_client_class: MagicMock) -> None:
    """Calling get_competition_ids without login should raise BetfairAuthError."""
    auth = BetfairAuth(_make_secrets())

    with pytest.raises(BetfairAuthError, match="Not authenticated"):
        await auth.get_competition_ids(["Premier League"])
