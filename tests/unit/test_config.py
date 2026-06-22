"""Unit tests for config loading and validation."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.config.settings import (
    AppConfig,
    ConfigError,
    SecretsConfig,
    StrategyConfig,
    load_config,
    load_secrets,
)
from tests.conftest import SAMPLE_CONFIG_YAML, SAMPLE_SECRETS_ENV


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


def test_load_config_valid(tmp_path: Path) -> None:
    """Valid YAML should parse into an AppConfig with all defaults."""
    cfg_file = tmp_path / "settings.yaml"
    cfg_file.write_text(SAMPLE_CONFIG_YAML, encoding="utf-8")

    config = load_config(cfg_file)

    assert config.strategy.max_entry_odds == 3.5
    assert config.strategy.stake == 10.0
    assert config.strategy.commission_rate == 0.05
    assert config.strategy.goal_spike_threshold == 0.30
    assert config.strategy.stop_loss_minute == 60
    assert config.strategy.min_market_volume == 50_000
    assert config.strategy.daily_loss_limit == 50.0
    assert config.strategy.max_open_positions == 3
    assert config.strategy.max_liability_per_bet == 5.0
    assert "Premier League" in config.streaming.target_competitions
    assert config.logging.level == "INFO"
    assert config.paper_mode is True


def test_load_config_missing_file(tmp_path: Path) -> None:
    """Non-existent file should raise ConfigError."""
    missing = tmp_path / "does_not_exist.yaml"

    with pytest.raises(ConfigError, match="not found"):
        load_config(missing)


def test_load_config_empty_yaml(tmp_path: Path) -> None:
    """Empty YAML file (parsed as None) should raise ConfigError."""
    cfg_file = tmp_path / "empty.yaml"
    cfg_file.write_text("", encoding="utf-8")

    with pytest.raises(ConfigError, match="empty"):
        load_config(cfg_file)


def test_load_config_invalid_yaml(tmp_path: Path) -> None:
    """Unparseable YAML should raise ConfigError."""
    cfg_file = tmp_path / "bad.yaml"
    cfg_file.write_text(": this is not valid yaml: :", encoding="utf-8")

    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_config(cfg_file)


def test_load_config_invalid_values(tmp_path: Path) -> None:
    """Out-of-range values should raise ConfigError with details."""
    bad_data = {
        "strategy": {"max_entry_odds": -1.0, "commission_rate": 2.5},
        "streaming": {},
    }
    cfg_file = tmp_path / "bad_values.yaml"
    cfg_file.write_text(yaml.dump(bad_data), encoding="utf-8")

    with pytest.raises(ConfigError, match="validation failed"):
        load_config(cfg_file)


# ---------------------------------------------------------------------------
# StrategyConfig validation
# ---------------------------------------------------------------------------


def test_strategy_config_defaults() -> None:
    """All fields should have sensible defaults."""
    cfg = StrategyConfig()
    assert cfg.max_entry_odds == 3.5
    assert cfg.stake == 10.0
    assert cfg.daily_loss_limit == 50.0
    assert cfg.max_open_positions == 3
    assert cfg.max_liability_per_bet == 5.0


def test_strategy_config_rejects_out_of_range() -> None:
    """Fields with ge/le should reject invalid values."""
    with pytest.raises(ValidationError):
        StrategyConfig(max_entry_odds=0.0)  # ge=1.0

    with pytest.raises(ValidationError):
        StrategyConfig(stake=-1.0)  # gt=0.0

    with pytest.raises(ValidationError):
        StrategyConfig(commission_rate=1.5)  # le=1.0


# ---------------------------------------------------------------------------
# SecretsConfig
# ---------------------------------------------------------------------------


def test_secrets_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Secrets should load from environment variables."""
    for key, value in SAMPLE_SECRETS_ENV.items():
        monkeypatch.setenv(key, value)

    secrets = SecretsConfig()  # type: ignore[call-arg]

    assert secrets.betfair_app_key == "test-app-key-123"
    assert secrets.betfair_username == "test_user"


def test_secrets_config_missing_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing required env vars should raise ConfigError via ValidationError."""
    # Clear env so required fields are absent
    for key in SAMPLE_SECRETS_ENV:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ConfigError):
        load_secrets()


def test_secrets_config_cert_file_must_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cert path pointing to a non-existent file should fail validation."""
    for key, value in SAMPLE_SECRETS_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("BETFAIR_CERT_PATH", "/nonexistent/cert.crt")

    with pytest.raises(ConfigError, match="not found"):
        load_secrets()
