"""Composite decision list engine for fail-safe gate evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from .models import Decision, EvaluationRequest
from .rules.base import Rule


class _ActuatorPort(Protocol):
    """Protocol for hardware actuator trip dispatching."""

    def dispatch_emergency_trip(self, regulator_id: str, reason: str) -> Any:
        """Dispatch an emergency trip to the physical actuator.

        Args:
            regulator_id: Target regulator gate identifier.
            reason: Diagnostic explanation for the emergency trip.
        """
        ...


class DecisionEngine:
    """Ordered rules engine executing business safety rules sequentially.

    Evaluates telemetry against an ordered sequence of rules with short-circuiting
    on the first safety envelope or variance violation.
    """

    def __init__(
        self,
        rules: Sequence[Rule],
        actuator_port: _ActuatorPort | None = None,
    ) -> None:
        """Initialize the decision engine with an ordered rule list.

        Args:
            rules: Ordered sequence of Rule implementations.
            actuator_port: Optional actuator port for immediate emergency trip dispatch.
        """
        self._rules = tuple(rules)
        self._actuator = actuator_port

    @property
    def rules(self) -> tuple[Rule, ...]:
        """Return the immutable tuple of registered rules."""
        return self._rules

    def evaluate(self, request: EvaluationRequest) -> Decision:
        """Evaluate telemetry across all registered rules in prioritized sequence.

        Args:
            request: Evaluation request containing telemetry data.

        Returns:
            Decision from the first tripping rule, or a PASS decision if all rules succeed.
        """
        for rule in self._rules:
            decision = rule.evaluate(request)
            if not decision.is_allowed:
                if decision.trip_required and self._actuator is not None:
                    self._actuator.dispatch_emergency_trip(
                        regulator_id=request.regulator_id,
                        reason=decision.reason,
                    )
                return decision

        return Decision(
            is_allowed=True,
            status_code=200,
            rule_id="PASS",
            reason="Telemetry passed all safety envelope and correlation checks.",
            trip_required=False,
            violating_rule_id=None,
        )
