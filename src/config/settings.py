"""Configuration models and loaders.

Strategy parameters come from config/settings.yaml (committable).
Secrets come from environment variables / .env (never committed).
Both are validated with Pydantic at startup — fail fast on any invalid value.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.exceptions import ConfigError

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


class StrategyConfig(BaseModel):
    """Trading strategy parameters. All values come from settings.yaml."""

    max_entry_odds: float = Field(default=3.5, ge=1.0, le=1000.0)
    stake: float = Field(default=10.0, gt=0.0)
    commission_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    goal_spike_threshold: float = Field(default=0.30, gt=0.0, le=1.0)
    stop_loss_minute: int = Field(default=60, ge=1, le=120)
    min_market_volume: float = Field(default=50_000, ge=0.0)
    daily_loss_limit: float = Field(default=50.0, ge=0.0)
    max_open_positions: int = Field(default=3, ge=1, le=20)
    max_liability_per_bet: float = Field(default=5.0, gt=0.0)


class StreamingConfig(BaseModel):
    """Streaming connection parameters. Reconnection is managed by flumine."""

    target_competitions: list[str] = Field(
        default=["Premier League", "Championship"],
        min_length=1,
    )
    market_countries: list[str] = Field(
        default=["GB", "DE", "ES", "IT", "FR", "NL", "PT"],
        description="ISO country codes passed to streaming filter to stay under the 200-market cap.",
    )


_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class LoggingConfig(BaseModel):
    level: str = Field(default="INFO")

    @field_validator("level")
    @classmethod
    def _validate_level(cls, v: str) -> str:
        upper = v.upper()
        if upper not in _VALID_LOG_LEVELS:
            raise ValueError(f"Invalid log level '{v}'. Must be one of {sorted(_VALID_LOG_LEVELS)}")
        return upper


class AppConfig(BaseModel):
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paper_mode: bool = Field(default=True)


class SecretsConfig(BaseSettings):
    """Secrets loaded from environment variables or .env file. Never log instances."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    betfair_app_key: str = Field(..., description="Betfair application key")
    betfair_username: str = Field(..., description="Betfair username")
    betfair_password: str = Field(default="", description="Betfair password")
    betfair_cert_path: Path = Field(..., description="Path to SSL certificate (.crt)")
    betfair_cert_key_path: Path = Field(..., description="Path to SSL private key (.key)")
    database_url: str = Field(
        default="postgresql+psycopg2://bot:bot_password@localhost:5432/betfair_ltd",
    )

    @field_validator("betfair_cert_path", "betfair_cert_key_path")
    @classmethod
    def _cert_file_exists(cls, v: Path) -> Path:
        if not v.is_file():
            raise ConfigError(f"Certificate file not found: {v}")
        return v


def load_config(path: Path | None = None) -> AppConfig:
    """Load and validate application configuration from a YAML file.

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
            f"Configuration validation failed ({len(errors)} error(s)):\n  " + "\n  ".join(errors)
        ) from exc


def load_secrets() -> SecretsConfig:
    """Load secrets from environment variables and .env file.

    Raises:
        ConfigError: If required secrets are missing or cert files don't exist.
    """
    try:
        return SecretsConfig()  # type: ignore[call-arg]
    except ValidationError as exc:
        errors = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        raise ConfigError(
            f"Secrets validation failed ({len(errors)} error(s)):\n  " + "\n  ".join(errors)
        ) from exc
