"""Unit tests for GoalDetector — pure logic, no mocking needed."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.exceptions import GoalDetectionError
from src.goal_detection.detector import GoalDetector, GoalDetectionResult


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_init_valid_threshold() -> None:
    """Should accept any threshold in (0, 1]."""
    detector = GoalDetector(0.30)
    assert detector._spike_threshold == Decimal("0.30")


def test_init_zero_threshold_raises() -> None:
    """Zero threshold should raise GoalDetectionError."""
    with pytest.raises(GoalDetectionError):
        GoalDetector(0.0)


def test_init_negative_threshold_raises() -> None:
    """Negative threshold should raise GoalDetectionError."""
    with pytest.raises(GoalDetectionError):
        GoalDetector(-0.1)


def test_init_over_one_threshold_raises() -> None:
    """Threshold > 1 should raise GoalDetectionError."""
    with pytest.raises(GoalDetectionError):
        GoalDetector(1.5)


# ---------------------------------------------------------------------------
# init_market / reset_market
# ---------------------------------------------------------------------------

def test_init_market_sets_state() -> None:
    """init_market should register a market for tracking."""
    detector = GoalDetector(0.30)
    detector.init_market("m1", Decimal("3.50"))
    assert "m1" in detector.active_markets


def test_init_market_idempotent() -> None:
    """Calling init_market twice should replace state silently."""
    detector = GoalDetector(0.30)
    detector.init_market("m1", Decimal("3.50"))
    detector.init_market("m1", Decimal("4.00"))  # new reference
    assert "m1" in detector.active_markets


def test_reset_market_removes_state() -> None:
    """reset_market should remove tracking."""
    detector = GoalDetector(0.30)
    detector.init_market("m1", Decimal("3.50"))
    detector.reset_market("m1")
    assert "m1" not in detector.active_markets


def test_reset_market_unknown_is_noop() -> None:
    """reset_market on an untracked market should not raise."""
    detector = GoalDetector(0.30)
    detector.reset_market("nonexistent")  # should not raise


def test_on_tick_without_init_raises() -> None:
    """on_tick should raise GoalDetectionError if init_market wasn't called."""
    detector = GoalDetector(0.30)
    with pytest.raises(GoalDetectionError):
        detector.on_tick(
            "unknown", Decimal("3.50"), Decimal("3.40"),
            datetime.now(UTC),
        )


# ---------------------------------------------------------------------------
# Spike detection
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 14, 15, 5, 0, tzinfo=UTC)


def test_no_spike_below_threshold() -> None:
    """A small price move should not trigger detection."""
    detector = GoalDetector(0.30)
    detector.init_market("m1", Decimal("3.50"))

    result = detector.on_tick("m1", Decimal("3.80"), Decimal("3.70"), NOW)
    # 3.80 vs 3.50 → spike = 0.30/3.50 = 0.0857 (8.6%) < 30%
    assert result.goal_detected is False
    assert result.confidence == 0.0


def test_spike_at_exact_threshold() -> None:
    """A move exactly at the threshold should trigger."""
    detector = GoalDetector(0.30)
    ref = Decimal("3.50")
    detector.init_market("m1", ref)

    # spike = 1.05/3.50 = 0.30 exactly
    spike_price = ref + (ref * Decimal("0.30"))
    result = detector.on_tick("m1", spike_price, Decimal("4.50"), NOW)
    assert result.goal_detected is True
    assert result.confidence >= 0.5


def test_spike_above_threshold() -> None:
    """A clear spike should trigger with high confidence."""
    detector = GoalDetector(0.30)
    ref = Decimal("3.00")
    detector.init_market("m1", ref)

    # First tick: small move (sets previous prices)
    detector.on_tick("m1", Decimal("3.10"), Decimal("3.00"), NOW)
    # Second tick: large spike with back confirmation
    result = detector.on_tick("m1", Decimal("4.50"), Decimal("4.20"), NOW)

    assert result.goal_detected is True
    # Both lay and back jumped from previous values → confidence 1.0
    assert result.confidence == 1.0


def test_spike_without_back_confirmation() -> None:
    """Spike without back price movement has lower confidence."""
    detector = GoalDetector(0.30)
    ref = Decimal("3.00")
    detector.init_market("m1", ref)

    # First tick sets previous values
    detector.on_tick("m1", Decimal("3.10"), Decimal("3.00"), NOW)
    # Second tick: lay spikes but back stays same
    result = detector.on_tick("m1", Decimal("4.50"), Decimal("3.00"), NOW)

    assert result.goal_detected is True
    assert result.confidence == 0.5  # spike alone, no back movement


def test_spike_zero_reference() -> None:
    """Zero reference price should not cause division error."""
    detector = GoalDetector(0.30)
    detector.init_market("m1", Decimal("0.00"))
    result = detector.on_tick("m1", Decimal("3.50"), Decimal("3.40"), NOW)
    assert result.goal_detected is False


def test_multiple_markets_isolated() -> None:
    """Each market's detection should be independent."""
    detector = GoalDetector(0.30)
    detector.init_market("m1", Decimal("3.00"))
    detector.init_market("m2", Decimal("5.00"))

    # m1 gets a spike, m2 doesn't
    r1 = detector.on_tick("m1", Decimal("4.00"), Decimal("3.80"), NOW)  # 33% spike
    r2 = detector.on_tick("m2", Decimal("5.10"), Decimal("4.90"), NOW)  # 2% move

    assert r1.goal_detected is True
    assert r2.goal_detected is False


def test_tick_history_capped() -> None:
    """Tick history should not grow unbounded."""
    detector = GoalDetector(0.30)
    detector.init_market("m1", Decimal("3.00"))

    for i in range(20):
        detector.on_tick(
            "m1",
            Decimal(str(3.0 + i * 0.01)),
            Decimal(str(2.9 + i * 0.01)),
            NOW,
        )

    # History shouldn't exceed _MAX_TICK_HISTORY (10)
    state = detector._states["m1"]
    assert len(state.tick_history) <= 10
