"""Sensor variance and frozen telemetry detection rule."""

from __future__ import annotations

from ..models import Decision, EvaluationRequest
from .base import Rule


class FrozenTelemetryRule(Rule):
    """Evaluates sliding-window telemetry to detect frozen sensors (zero variance)."""

    def __init__(
        self,
        min_samples: int = 5,
        min_variance_epsilon: float = 1e-5,
    ) -> None:
        """Initialize the frozen telemetry rule.

        Args:
            min_samples: Minimum sliding-window history samples required for evaluation.
            min_variance_epsilon: Minimum variance threshold below which signal is considered frozen.
        """
        self._min_samples = min_samples
        self._min_variance_epsilon = min_variance_epsilon

    @property
    def rule_id(self) -> str:
        """Return the unique rule identifier."""
        return "R-VAR-03"

    def evaluate(self, request: EvaluationRequest) -> Decision:
        """Evaluate history samples for lack of variance.

        Args:
            request: Evaluation request containing telemetry and sliding history.

        Returns:
            Decision indicating whether sensor variance is healthy or frozen.
        """
        samples = list(request.recent_history)
        if request.telemetry is not None:
            samples.append(request.telemetry)

        if len(samples) < self._min_samples:
            return Decision(
                is_allowed=True,
                status_code=200,
                rule_id=self.rule_id,
                reason="Insufficient sliding history samples for variance evaluation.",
                trip_required=False,
                violating_rule_id=None,
                diagnostics={
                    "samples_count": len(samples),
                    "min_required": self._min_samples,
                },
            )

        flow_values = [s.flow_rate for s in samples]
        mean = sum(flow_values) / len(flow_values)
        variance = sum((x - mean) ** 2 for x in flow_values) / len(flow_values)

        if variance <= self._min_variance_epsilon:
            return Decision(
                is_allowed=False,
                status_code=422,
                rule_id=self.rule_id,
                reason=(
                    f"Frozen telemetry detected: sample variance {variance:.8f} is below "
                    f"threshold {self._min_variance_epsilon:.8f} across {len(samples)} samples."
                ),
                trip_required=True,
                violating_rule_id=self.rule_id,
                diagnostics={
                    "variance": variance,
                    "threshold": self._min_variance_epsilon,
                    "samples_count": len(samples),
                },
            )

        return Decision(
            is_allowed=True,
            status_code=200,
            rule_id=self.rule_id,
            reason="Telemetry variance is healthy.",
            trip_required=False,
            violating_rule_id=None,
            diagnostics={
                "variance": variance,
                "threshold": self._min_variance_epsilon,
                "samples_count": len(samples),
            },
        )
