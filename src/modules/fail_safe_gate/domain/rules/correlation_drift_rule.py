"""Thermodynamic pressure-temperature correlation drift evaluation rule."""

from __future__ import annotations

from ..models import Decision, EvaluationRequest
from .base import Rule


class CorrelationDriftRule(Rule):
    """Evaluates telemetry flow rate against ideal gas thermodynamic correlation."""

    def __init__(
        self,
        k_factor: float = 10553.4,
        tolerance_sigma: float = 3.0,
        sigma_base: float = 28.0,
    ) -> None:
        """Initialize the correlation drift rule.

        Args:
            k_factor: Characteristic thermodynamic gas constant multiplier.
            tolerance_sigma: Multiplier for standard deviation tolerance envelope.
            sigma_base: Baseline standard deviation for flow residuals in Sm3/h.
        """
        self._k_factor = k_factor
        self._tolerance_sigma = tolerance_sigma
        self._sigma_base = sigma_base

    @property
    def rule_id(self) -> str:
        """Return the unique rule identifier."""
        return "R-CORR-02"

    def evaluate(self, request: EvaluationRequest) -> Decision:
        """Evaluate flow against pressure-temperature correlation envelope.

        Args:
            request: Evaluation request containing telemetry data.

        Returns:
            Decision indicating whether correlation residual is acceptable.
        """
        t = request.telemetry
        if t.temperature <= 0.0 or t.pressure <= 0.0:
            return Decision(
                is_allowed=False,
                status_code=422,
                rule_id=self.rule_id,
                reason="Invalid thermodynamic state: pressure and temperature must be positive.",
                trip_required=True,
                violating_rule_id=self.rule_id,
                diagnostics={
                    "pressure": t.pressure,
                    "temperature": t.temperature,
                },
            )

        # Theoretical expected flow from ideal gas law: Q = k * (P / T)
        expected_flow = self._k_factor * (t.pressure / t.temperature)
        residual = abs(t.flow_rate - expected_flow)
        max_allowed_residual = self._tolerance_sigma * self._sigma_base

        if residual > max_allowed_residual:
            return Decision(
                is_allowed=False,
                status_code=422,
                rule_id=self.rule_id,
                reason=(
                    f"Correlation drift detected: residual {residual:.2f} Sm3/h exceeds "
                    f"{self._tolerance_sigma:.1f}-sigma threshold of {max_allowed_residual:.2f} Sm3/h."
                ),
                trip_required=True,
                violating_rule_id=self.rule_id,
                diagnostics={
                    "measured_flow": t.flow_rate,
                    "expected_flow": expected_flow,
                    "residual": residual,
                    "threshold": max_allowed_residual,
                },
            )

        return Decision(
            is_allowed=True,
            status_code=200,
            rule_id=self.rule_id,
            reason="Pressure-temperature dynamic correlation envelope satisfied.",
            trip_required=False,
            violating_rule_id=None,
            diagnostics={
                "measured_flow": t.flow_rate,
                "expected_flow": expected_flow,
                "residual": residual,
                "threshold": max_allowed_residual,
            },
        )
