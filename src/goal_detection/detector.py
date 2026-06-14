"""Price-spike goal detection for LTD strategy.

Monitors the draw runner's lay price after entry.  A goal is signalled
when the lay price jumps by at least ``spike_threshold`` relative to
the reference price at entry.  Back-price movement is used as a
confirmation signal to increase confidence.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Deque, Tuple

from src.exceptions import GoalDetectionError

logger = logging.getLogger(__name__)

# Maximum number of recent ticks kept per market.
_MAX_TICK_HISTORY = 10


@dataclass(frozen=True)
class GoalDetectionResult:
    """Outcome of a goal-detection evaluation on a single tick.

    Attributes:
        goal_detected: ``True`` if a goal is likely to have been scored.
        confidence: A value between 0.0 and 1.0 indicating confidence.
        reason: Human-readable explanation of the detection outcome.
    """

    goal_detected: bool
    confidence: float
    reason: str


@dataclass
class _GoalState:
    """Per-market state tracked between ticks."""

    market_id: str
    reference_lay_price: Decimal
    last_lay_price: Decimal | None = None
    last_back_price: Decimal | None = None
    tick_history: Deque[Tuple[Decimal, Decimal]] = field(
        default_factory=lambda: deque(maxlen=_MAX_TICK_HISTORY)
    )


class GoalDetector:
    """Detect goals via draw-price movement.

    Pure analysis — no I/O, no DB access.  One instance per bot run,
    tracking multiple markets concurrently.

    Args:
        spike_threshold: Minimum relative price increase (e.g. 0.30 for
            30 %) that triggers a goal detection.
    """

    def __init__(self, spike_threshold: float) -> None:
        if not (0.0 < spike_threshold <= 1.0):
            raise GoalDetectionError(
                f"spike_threshold must be in (0, 1], got {spike_threshold}"
            )
        self._spike_threshold = Decimal(str(spike_threshold))
        self._states: dict[str, _GoalState] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init_market(self, market_id: str, reference_lay_price: Decimal) -> None:
        """Set the reference price when a lay position is opened.

        Must be called before ``on_tick`` for the given market.
        Replaces any existing state for the market (idempotent).

        Args:
            market_id: Unique market identifier string.
            reference_lay_price: The lay price at which the entry
                order was matched.
        """
        self._states[market_id] = _GoalState(
            market_id=market_id,
            reference_lay_price=reference_lay_price,
        )
        logger.debug(
            "GoalDetector initialised for %s (ref=%.2f)",
            market_id, reference_lay_price,
        )

    def on_tick(
        self,
        market_id: str,
        draw_lay_price: Decimal,
        draw_back_price: Decimal,
        timestamp: datetime,  # noqa: ARG002  reserved for future smoothing
    ) -> GoalDetectionResult:
        """Evaluate one tick for a goal signal.

        Args:
            market_id: Market to check.
            draw_lay_price: Current best lay price for the draw runner.
            draw_back_price: Current best back price for the draw runner.
            timestamp: UTC time of the tick (unused currently; reserved
                for future time-weighted smoothing).

        Returns:
            ``GoalDetectionResult`` with detection outcome.

        Raises:
            GoalDetectionError: If ``init_market`` has not been called
                for this market.
        """
        try:
            state = self._states[market_id]
        except KeyError:
            raise GoalDetectionError(
                f"Market {market_id} not initialised — call init_market first"
            )

        # Store previous values for meta-checks
        previous_lay = state.last_lay_price
        previous_back = state.last_back_price

        state.last_lay_price = draw_lay_price
        state.last_back_price = draw_back_price
        state.tick_history.append((draw_lay_price, draw_back_price))

        # --- Spike detection ---
        ref = state.reference_lay_price
        if ref == Decimal("0"):
            return GoalDetectionResult(
                goal_detected=False, confidence=0.0,
                reason="Reference price is zero — cannot compute spike",
            )

        relative_spike = (draw_lay_price - ref) / ref

        if relative_spike < self._spike_threshold:
            return GoalDetectionResult(
                goal_detected=False, confidence=0.0,
                reason=f"Spike {relative_spike:.1%} below threshold {self._spike_threshold:.1%}",
            )

        # --- Confirmation: back price moving in same direction ---
        confidence = 0.5  # Base: spike alone
        if previous_back is not None and draw_back_price > previous_back:
            # Back price also jumped (market now thinks draw is less likely)
            confidence = 0.8
        if (
            previous_back is not None
            and previous_lay is not None
            and draw_back_price > previous_back
            and draw_lay_price > previous_lay
        ):
            # Both prices moved sharply in the same tick
            confidence = 1.0

        return GoalDetectionResult(
            goal_detected=True,
            confidence=confidence,
            reason=f"Price spike {relative_spike:.1%} detected",
        )

    def reset_market(self, market_id: str) -> None:
        """Remove tracking data when a trade is closed.

        Safe to call for an already-removed market (no-op).

        Args:
            market_id: Market to clean up.
        """
        removed = self._states.pop(market_id, None)
        if removed:
            logger.debug("GoalDetector reset for %s", market_id)

    @property
    def active_markets(self) -> set[str]:
        """Return the set of market IDs currently being tracked."""
        return set(self._states.keys())
