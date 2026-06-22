"""Betfair API authentication with SSL certificate.

Handles login, session token management, and competition ID resolution.
"""

from __future__ import annotations

import logging

import betfairlightweight
from betfairlightweight import APIClient

from src.config.settings import SecretsConfig
from src.exceptions import BetfairAuthError

logger = logging.getLogger(__name__)


class BetfairAuth:
    """Authenticate with Betfair and resolve competition metadata."""

    def __init__(self, secrets: SecretsConfig) -> None:
        self._app_key = secrets.betfair_app_key
        self._username = secrets.betfair_username
        self._password = secrets.betfair_password
        self._cert_path = str(secrets.betfair_cert_path)
        self._cert_key_path = str(secrets.betfair_cert_key_path)
        self._client: APIClient | None = None

    def login(self) -> APIClient:
        """Authenticate with Betfair using the SSL certificate.

        Returns:
            An authenticated APIClient instance.

        Raises:
            BetfairAuthError: If login fails.
        """
        self._client = betfairlightweight.APIClient(
            username=self._username,
            password=self._password,
            app_key=self._app_key,
            cert_files=(self._cert_path, self._cert_key_path),
        )
        try:
            self._client.login()
            logger.info("Betfair login successful")
            return self._client
        except Exception as exc:
            raise BetfairAuthError(f"Betfair login failed: {exc}") from exc

    @property
    def session_token(self) -> str | None:
        """Return the current session token, or None if not logged in."""
        if self._client is None:
            return None
        return self._client.session_token

    def get_competition_ids(self, competition_names: list[str]) -> dict[str, str]:
        """Resolve competition names to Betfair IDs (football only, event type 1).

        Returns:
            A dict mapping found names to their Betfair competition IDs.

        Raises:
            BetfairAuthError: If not authenticated or the API call fails.
        """
        if self._client is None:
            raise BetfairAuthError("Not authenticated. Call login() first.")

        logger.info("Resolving competition IDs for: %s", competition_names)
        try:
            competitions = self._client.list_competitions(
                market_filter={"eventTypeIds": ["1"]},
            )
        except Exception as exc:
            raise BetfairAuthError(f"Failed to list competitions: {exc}") from exc

        available: dict[str, str] = {
            comp.competition.name.upper(): comp.competition.id
            for comp in competitions
            if getattr(comp.competition, "name", None) and getattr(comp.competition, "id", None)
        }

        result: dict[str, str] = {}
        for target in competition_names:
            comp_id = available.get(target.upper())
            if comp_id:
                result[target] = comp_id
            else:
                logger.warning("Competition not found: %s", target)

        logger.info("Resolved %d/%d competition(s)", len(result), len(competition_names))
        return result
