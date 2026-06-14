"""Exception hierarchy for the Betfair LTD trading bot.

All application-level errors inherit from BetfairBotError, allowing
a single top-level catch in main.py for clean shutdown.
"""


class BetfairBotError(Exception):
    """Base exception for all bot errors."""


class ConfigError(BetfairBotError):
    """Configuration loading or validation failure."""


class BetfairAuthError(BetfairBotError):
    """Betfair authentication failure (login, session, or cert)."""


class BetfairStreamError(BetfairBotError):
    """Betfair streaming connection failure or reconnection exhausted."""


class DatabaseError(BetfairBotError):
    """Database operation failure (connection, constraint, query)."""


class StrategyError(BetfairBotError):
    """Strategy execution failure (entry/exit conditions, state machine)."""


class GoalDetectionError(BetfairBotError):
    """Goal detection configuration or state error."""
