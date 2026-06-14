"""Configuration models and loaders.

Strategy parameters come from config/settings.yaml (committable).
Secrets come from environment variables / .env (never committed).

Both are validated with Pydantic at startup — fail fast on any invalid value.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import override

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.exceptions import ConfigError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


# ---------------------------------------------------------------------------
# Strategy config
# ---------------------------------------------------------------------------

class StrategyConfig(BaseModel):
    """Trading strategy parameters. All values come from settings.yaml."""

    max_entry_odds: float = Field(
        default=3.5, ge=1.0, le=1000.0,
        description="Maximum draw lay odds for entry"
    )
    stake: float = Field(
        default=10.0, gt=0.0,
        description="Lay stake per trade in GBP"
    )
    commission_rate: float = Field(
        default=0.05, ge=0.0, le=1.0,
        description="Betfair commission rate (5% = 0.05)"
    )
    goal_spike_threshold: float = Field(
        default=0.30, gt=0.0, le=1.0,
        description="Minimum relative price spike to trigger goal detection"
    )
    stop_loss_minute: int = Field(
        default=60, ge=1, le=120,
        description="Match minute to exit if no goal scored"
    )
    min_market_volume: float = Field(
        default=50_000, ge=0.0,
        description="Minimum pre-kick-off matched volume in GBP"
    )
    daily_loss_limit: float = Field(
        default=50.0, ge=0.0,
        description="Hard daily P&L loss limit (kill switch)"
    )


# ---------------------------------------------------------------------------
# Streaming config
# ---------------------------------------------------------------------------

class StreamingConfig(BaseModel):
    """Streaming connection parameters."""

    target_competitions: list[str] = Field(
        default=["Premier League", "Championship"],
        min_length=1,
        description="Competition names to subscribe to"
    )
    max_reconnect_attempts: int = Field(
        default=5, ge=0, le=20,
        description="Maximum reconnection attempts after a drop"
    )
    reconnect_base_delay_s: float = Field(
        default=1.0, gt=0.0,
        description="Base delay in seconds for exponential backoff"
    )


# ---------------------------------------------------------------------------
# Logging config
# ---------------------------------------------------------------------------

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = Field(
        default="INFO",
        description="Python logging level name"
    )

    @field_validator("level")
    @classmethod
    def _validate_level(cls, v: str) -> str:
        upper = v.upper()
        if upper not in _VALID_LOG_LEVELS:
            raise ValueError(f"Invalid log level '{v}'. Must be one of {sorted(_VALID_LOG_LEVELS)}")
        return upper


# ---------------------------------------------------------------------------
# Aggregate app config
# ---------------------------------------------------------------------------

class AppConfig(BaseModel):
    """Top-level application configuration loaded from settings.yaml."""

    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


# ---------------------------------------------------------------------------
# Secrets (env vars)
# ---------------------------------------------------------------------------

class SecretsConfig(BaseSettings):
    """Secrets loaded from environment variables or .env file.

    Never log instances of this class.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    betfair_app_key: str = Field(..., description="Betfair application key")
    betfair_username: str = Field(..., description="Betfair username")
    betfair_password: str = Field(
        default="",
        description="Betfair password (may be empty when using cert-only auth)",
    )
    betfair_cert_path: Path = Field(..., description="Path to SSL certificate (.crt)")
    betfair_cert_key_path: Path = Field(..., description="Path to SSL private key (.key)")
    database_url: str = Field(
        default="postgresql+asyncpg://bot:bot_password@localhost:5432/betfair_ltd",
        description="Async PostgreSQL connection URL"
    )

    @field_validator("betfair_cert_path", "betfair_cert_key_path")
    @classmethod
    def _cert_file_exists(cls, v: Path) -> Path:
        if not v.is_file():
            raise ConfigError(f"Certificate file not found: {v}")
        return v


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_config(path: Path | None = None) -> AppConfig:
    """Load and validate application configuration from a YAML file.

    Args:
        path: Path to settings.yaml. Defaults to config/settings.yaml.

    Returns:
        Validated AppConfig instance.

    Raises:
        ConfigError: If the file is missing, unparseable, or contains invalid values.
    """
    file_path = path or CONFIG_DIR / "settings.yaml"

    if not file_path.is_file():
        raise ConfigError(f"Configuration file not found: {file_path}")

    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {file_path}: {exc}") from exc

    if raw is None:
        raise ConfigError(f"Configuration file is empty: {file_path}")

    try:
        return AppConfig(**raw)
    except ValidationError as exc:
        errors = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        raise ConfigError(
            f"Configuration validation failed ({len(errors)} error(s)):\n  "
            + "\n  ".join(errors)
        ) from exc


def load_secrets() -> SecretsConfig:
    """Load secrets from environment variables and .env file.

    Returns:
        Validated SecretsConfig instance.

    Raises:
        ConfigError: If required secrets are missing or cert files don't exist.
    """
    try:
        return SecretsConfig()  # type: ignore[call-arg]
    except ValidationError as exc:
        errors = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        raise ConfigError(
            f"Secrets validation failed ({len(errors)} error(s)):\n  "
            + "\n  ".join(errors)
        ) from exc
