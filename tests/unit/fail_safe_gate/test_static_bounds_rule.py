"""Unit tests for StaticBoundsRule."""

from src.modules.fail_safe_gate.domain.models import (
    EvaluationRequest,
    TelemetryData,
)
from src.modules.fail_safe_gate.domain.rules.static_bounds_rule import (
    StaticBoundsRule,
)


def _create_request(flow: float) -> EvaluationRequest:
    return EvaluationRequest(
        request_id="req-test",
        regulator_id="reg-1",
        telemetry=TelemetryData(
            sensor_id="sensor-1",
            flow_rate=flow,
            pressure=10.0,
            temperature=293.15,
            timestamp_ns=1_000_000,
        ),
    )


def test_static_bounds_rule_within_bounds() -> None:
    """[US-1][AC-1.2] Verify nominal flow within [0.0, 1200.0] passes."""
    rule = StaticBoundsRule(min_flow=0.0, max_flow=1200.0)
    assert rule.rule_id == "R-STATIC-01"

    req = _create_request(450.0)
    decision = rule.evaluate(req)

    assert decision.is_allowed is True
    assert decision.status_code == 200
    assert decision.trip_required is False
    assert decision.violating_rule_id is None


def test_static_bounds_rule_exceeds_max() -> None:
    """[US-1][AC-1.2] Verify flow above 1200.0 trips static envelope."""
    rule = StaticBoundsRule(min_flow=0.0, max_flow=1200.0)

    req = _create_request(1500.0)
    decision = rule.evaluate(req)

    assert decision.is_allowed is False
    assert decision.status_code == 422
    assert decision.trip_required is True
    assert decision.rule_id == "R-STATIC-01"
    assert decision.violating_rule_id == "R-STATIC-01"
    assert "exceeds maximum" in decision.reason
    assert decision.diagnostics is not None
    assert decision.diagnostics["flow_rate"] == 1500.0


def test_static_bounds_rule_below_min() -> None:
    """[US-1][AC-1.2] Verify negative flow below 0.0 trips static envelope."""
    rule = StaticBoundsRule(min_flow=0.0, max_flow=1200.0)

    req = _create_request(-5.0)
    decision = rule.evaluate(req)

    assert decision.is_allowed is False
    assert decision.status_code == 422
    assert decision.trip_required is True
    assert decision.violating_rule_id == "R-STATIC-01"
    assert "below minimum" in decision.reason
