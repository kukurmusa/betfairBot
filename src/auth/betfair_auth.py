"""Betfair API authentication with SSL certificate.

Handles login, session token management, and competition ID resolution.
All synchronous betfairlightweight calls are wrapped in ``asyncio.to_thread``
to keep the async event loop free.
"""

from __future__ import annotations

import asyncio
import logging

import betfairlightweight
from betfairlightweight import APIClient

from src.config.settings import SecretsConfig
from src.exceptions import BetfairAuthError

logger = logging.getLogger(__name__)


class BetfairAuth:
    """Authenticate with Betfair and resolve competition metadata.

    The SSL cert paths and app key come from ``SecretsConfig`` — never
    hardcoded and never logged.
    """

    def __init__(self, secrets: SecretsConfig) -> None:
        self._app_key = secrets.betfair_app_key
        self._username = secrets.betfair_username
        self._password = secrets.betfair_password
        self._cert_path = str(secrets.betfair_cert_path)
        self._cert_key_path = str(secrets.betfair_cert_key_path)
        self._client: APIClient | None = None

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def login(self) -> APIClient:
        """Authenticate with Betfair using the SSL certificate.

        The synchronous ``APIClient.login()`` call runs in a thread to
        avoid blocking the event loop.

        Returns:
            An authenticated APIClient instance.

        Raises:
            BetfairAuthError: If login fails for any reason (network,
                invalid credentials, expired cert, etc.).
        """
        self._client = betfairlightweight.APIClient(
            username=self._username,
            password=self._password,
            app_key=self._app_key,
            cert_files=(self._cert_path, self._cert_key_path),
        )
        try:
            await asyncio.to_thread(self._client.login)
            logger.info("Betfair login successful")
            return self._client
        except Exception as exc:
            raise BetfairAuthError(f"Betfair login failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Session token
    # ------------------------------------------------------------------

    @property
    def session_token(self) -> str | None:
        """Return the current session token, or None if not logged in."""
        if self._client is None:
            return None
        return self._client.session_token

    # ------------------------------------------------------------------
    # Competition resolution
    # ------------------------------------------------------------------

    async def get_competition_ids(
        self, competition_names: list[str]
    ) -> dict[str, str]:
        """Resolve human-readable competition names to Betfair competition IDs.

        Calls the Betfair ``listCompetitions`` endpoint for soccer (event type 1)
        and matches the supplied names case-insensitively.

        Args:
            competition_names: List of competition names to look up
                (e.g. ``["Premier League", "Championship"]``).

        Returns:
            A dict mapping found competition names to their Betfair IDs.
            Names not found in the API response are omitted and a warning
            is logged for each.

        Raises:
            BetfairAuthError: If not authenticated or the API call fails.
        """
        if self._client is None:
            raise BetfairAuthError("Not authenticated. Call login() first.")

        logger.info("Resolving competition IDs for: %s", competition_names)

        try:
            competitions = await asyncio.to_thread(
                self._client.list_competitions,
                market_filter={"eventTypeIds": ["1"]},
            )
        except Exception as exc:
            raise BetfairAuthError(
                f"Failed to list competitions: {exc}"
            ) from exc

        # Build a lookup: uppercase name -> competition id
        available: dict[str, str] = {}
        for comp in competitions:
            name = getattr(comp.competition, "name", None)
            comp_id = getattr(comp.competition, "id", None)
            if name and comp_id:
                available[name.upper()] = comp_id

        # Match requested names
        result: dict[str, str] = {}
        for target in competition_names:
            comp_id = available.get(target.upper())
            if comp_id:
                result[target] = comp_id
            else:
                logger.warning(
                    "Competition not found in Betfair data: %s", target
                )

        if not result:
            logger.warning(
                "None of the target competitions were found. "
                "Stream will receive no market data."
            )

        logger.info("Resolved %d/%d competition(s)", len(result), len(competition_names))
        return result
