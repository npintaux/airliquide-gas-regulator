"""Base abstract rule definition for the Fail-Safe Gate decision-list pattern."""

from __future__ import annotations

import abc

from ..models import Decision, EvaluationRequest


class Rule(abc.ABC):
    """Abstract Base Class for individual fail-safe gate evaluation predicates."""

    @property
    @abc.abstractmethod
    def rule_id(self) -> str:
        """Unique rule identifier (e.g., 'R-STATIC-01', 'R-CORR-02')."""
        ...

    @abc.abstractmethod
    def evaluate(self, request: EvaluationRequest) -> Decision:
        """Evaluate telemetry against rule criteria.

        Args:
            request: Immutable domain evaluation request containing telemetry data.

        Returns:
            Decision instance indicating whether the telemetry is allowed or tripped.
        """
        ...
