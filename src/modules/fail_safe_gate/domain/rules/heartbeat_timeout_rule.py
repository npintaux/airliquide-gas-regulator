"""Sensor heartbeat timeout and interval check rule."""

from __future__ import annotations

from ..models import Decision, EvaluationRequest
from .base import Rule


class HeartbeatTimeoutRule(Rule):
    """Evaluates telemetry timestamp intervals to detect missing sensor heartbeats."""

    def __init__(self, max_interval_ms: float = 250.0) -> None:
        """Initialize heartbeat timeout rule.

        Args:
            max_interval_ms: Maximum allowable interval between consecutive telemetry samples in ms.
        """
        self._max_interval_ms = max_interval_ms

    @property
    def rule_id(self) -> str:
        """Return the unique rule identifier."""
        return "R-HEARTBEAT-04"

    def evaluate(self, request: EvaluationRequest) -> Decision:
        """Evaluate timestamp gap between recent telemetry frames.

        Args:
            request: Evaluation request containing telemetry and sliding history.

        Returns:
            Decision indicating whether heartbeat timing is acceptable.
        """
        if not request.recent_history:
            return Decision(
                is_allowed=True,
                status_code=200,
                rule_id=self.rule_id,
                reason="No preceding history available; initial heartbeat accepted.",
                trip_required=False,
                violating_rule_id=None,
            )

        last_sample = request.recent_history[-1]
        gap_ns = request.telemetry.timestamp_ns - last_sample.timestamp_ns
        gap_ms = gap_ns / 1_000_000.0

        if gap_ms > self._max_interval_ms:
            return Decision(
                is_allowed=False,
                status_code=422,
                rule_id=self.rule_id,
                reason=(
                    f"Heartbeat timeout detected: interval {gap_ms:.2f}ms exceeds "
                    f"maximum threshold of {self._max_interval_ms:.2f}ms."
                ),
                trip_required=True,
                violating_rule_id=self.rule_id,
                diagnostics={
                    "interval_ms": gap_ms,
                    "threshold_ms": self._max_interval_ms,
                },
            )

        return Decision(
            is_allowed=True,
            status_code=200,
            rule_id=self.rule_id,
            reason="Telemetry heartbeat interval is healthy.",
            trip_required=False,
            violating_rule_id=None,
            diagnostics={
                "interval_ms": gap_ms,
                "threshold_ms": self._max_interval_ms,
            },
        )
