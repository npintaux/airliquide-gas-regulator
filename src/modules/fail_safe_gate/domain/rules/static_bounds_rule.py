"""Static safety bounds evaluation rule."""

from __future__ import annotations

from ..models import Decision, EvaluationRequest
from .base import Rule


class StaticBoundsRule(Rule):
    """Evaluates telemetry flow rate against predefined static bounds."""

    def __init__(self, min_flow: float = 0.0, max_flow: float = 1200.0) -> None:
        """Initialize the static bounds rule.

        Args:
            min_flow: Minimum allowable flow rate in Sm3/h.
            max_flow: Maximum allowable flow rate in Sm3/h.
        """
        self._min_flow = min_flow
        self._max_flow = max_flow

    @property
    def rule_id(self) -> str:
        """Return the unique rule identifier."""
        return "R-STATIC-01"

    def evaluate(self, request: EvaluationRequest) -> Decision:
        """Evaluate flow rate against absolute static safety bounds.

        Args:
            request: Evaluation request containing telemetry data.

        Returns:
            Decision indicating whether flow rate is within bounds or tripped.
        """
        flow = request.telemetry.flow_rate
        if flow < self._min_flow:
            return Decision(
                is_allowed=False,
                status_code=422,
                rule_id=self.rule_id,
                reason=f"Flow rate {flow:.2f} Sm3/h is below minimum limit of {self._min_flow:.2f} Sm3/h.",
                trip_required=True,
                violating_rule_id=self.rule_id,
                diagnostics={
                    "flow_rate": flow,
                    "min_flow": self._min_flow,
                    "max_flow": self._max_flow,
                },
            )
        if flow > self._max_flow:
            return Decision(
                is_allowed=False,
                status_code=422,
                rule_id=self.rule_id,
                reason=f"Flow rate {flow:.2f} Sm3/h exceeds maximum limit of {self._max_flow:.2f} Sm3/h.",
                trip_required=True,
                violating_rule_id=self.rule_id,
                diagnostics={
                    "flow_rate": flow,
                    "min_flow": self._min_flow,
                    "max_flow": self._max_flow,
                },
            )

        return Decision(
            is_allowed=True,
            status_code=200,
            rule_id=self.rule_id,
            reason="Flow rate is within acceptable static safety bounds.",
            trip_required=False,
            violating_rule_id=None,
            diagnostics={
                "flow_rate": flow,
                "min_flow": self._min_flow,
                "max_flow": self._max_flow,
            },
        )
