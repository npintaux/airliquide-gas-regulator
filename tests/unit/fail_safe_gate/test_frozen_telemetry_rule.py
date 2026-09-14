"""Unit tests for FrozenTelemetryRule."""

from src.modules.fail_safe_gate.domain.models import (
    EvaluationRequest,
    TelemetryData,
)
from src.modules.fail_safe_gate.domain.rules.frozen_telemetry_rule import (
    FrozenTelemetryRule,
)


def _point(flow: float, pressure: float, temp: float, ts: int) -> TelemetryData:
    return TelemetryData(
        sensor_id="sensor-001",
        flow_rate=flow,
        pressure=pressure,
        temperature=temp,
        timestamp_ns=ts,
    )


def test_frozen_telemetry_sufficient_variance() -> None:
    """[US-2][AC-2.2] Verify dynamic varying telemetry passes."""
    rule = FrozenTelemetryRule(min_samples=5, min_variance_epsilon=1e-5)
    assert rule.rule_id == "R-VAR-03"

    history = tuple(
        _point(450.0 + i * 2.0, 12.5 + i * 0.1, 293.15, 1_000_000 + i * 100_000_000)
        for i in range(5)
    )
    req = EvaluationRequest(
        request_id="req-1",
        regulator_id="reg-1",
        telemetry=_point(460.0, 13.0, 293.15, 1_500_000_000),
        recent_history=history,
    )
    decision = rule.evaluate(req)
    assert decision.is_allowed is True
    assert decision.status_code == 200
    assert decision.trip_required is False
    assert decision.violating_rule_id is None


def test_frozen_telemetry_freeze_detected() -> None:
    """[US-2][AC-2.2] Verify identical readings over sliding window trip rule."""
    rule = FrozenTelemetryRule(min_samples=5, min_variance_epsilon=1e-5)

    history = tuple(
        _point(450.0, 12.5, 293.15, 1_000_000 + i * 100_000_000) for i in range(5)
    )
    req = EvaluationRequest(
        request_id="req-2",
        regulator_id="reg-1",
        telemetry=_point(450.0, 12.5, 293.15, 1_500_000_000),
        recent_history=history,
    )
    decision = rule.evaluate(req)
    assert decision.is_allowed is False
    assert decision.status_code == 422
    assert decision.trip_required is True
    assert decision.violating_rule_id == "R-VAR-03"
    assert "Frozen telemetry detected" in decision.reason
    assert decision.diagnostics is not None
    assert decision.diagnostics["variance"] <= 1e-5


def test_frozen_telemetry_insufficient_history() -> None:
    """[US-2][AC-2.2] Verify insufficient history does not trip freeze rule."""
    rule = FrozenTelemetryRule(min_samples=5)
    req = EvaluationRequest(
        request_id="req-3",
        regulator_id="reg-1",
        telemetry=_point(450.0, 12.5, 293.15, 1_000_000),
        recent_history=(),
    )
    decision = rule.evaluate(req)
    assert decision.is_allowed is True
    assert decision.status_code == 200
