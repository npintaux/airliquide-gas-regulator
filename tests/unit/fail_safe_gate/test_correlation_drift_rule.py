"""Unit tests for CorrelationDriftRule."""

from src.modules.fail_safe_gate.domain.models import (
    EvaluationRequest,
    TelemetryData,
)
from src.modules.fail_safe_gate.domain.rules.correlation_drift_rule import (
    CorrelationDriftRule,
)


def _req(flow: float, pressure: float, temp: float) -> EvaluationRequest:
    return EvaluationRequest(
        request_id="req-corr",
        regulator_id="reg-alpha",
        telemetry=TelemetryData(
            sensor_id="sensor-001",
            flow_rate=flow,
            pressure=pressure,
            temperature=temp,
            timestamp_ns=1_000_000_000,
        ),
    )


def test_correlation_drift_nominal() -> None:
    """[US-1][AC-1.3] Verify nominal pressure/temperature correlation passes."""
    rule = CorrelationDriftRule(k_factor=10553.4, tolerance_sigma=3.0)
    assert rule.rule_id == "R-CORR-02"

    # Nominal: flow=450.0, pressure=12.5 bar, temperature=293.15 K
    # Expected flow ~ 10553.4 * (12.5 / 293.15) = 450.0
    req = _req(450.0, 12.5, 293.15)
    decision = rule.evaluate(req)

    assert decision.is_allowed is True
    assert decision.status_code == 200
    assert decision.trip_required is False
    assert decision.violating_rule_id is None


def test_correlation_drift_detected() -> None:
    """[US-1][AC-1.3] Verify deviation beyond 3-sigma tolerance trips correlation rule."""
    rule = CorrelationDriftRule(k_factor=10553.4, tolerance_sigma=3.0)

    # Expected flow is ~450.0, but measured flow is 650.0 (drift)
    req = _req(650.0, 12.5, 293.15)
    decision = rule.evaluate(req)

    assert decision.is_allowed is False
    assert decision.status_code == 422
    assert decision.trip_required is True
    assert decision.rule_id == "R-CORR-02"
    assert decision.violating_rule_id == "R-CORR-02"
    assert "Correlation drift" in decision.reason
    assert decision.diagnostics is not None
    assert "residual" in decision.diagnostics


def test_correlation_invalid_temperature_or_pressure() -> None:
    """[US-1][AC-1.3] Verify non-positive temperature or pressure trips rule."""
    rule = CorrelationDriftRule()
    req_zero_temp = _req(450.0, 12.5, 0.0)
    decision = rule.evaluate(req_zero_temp)
    assert decision.is_allowed is False
    assert decision.status_code == 422
    assert "temperature must be positive" in decision.reason
