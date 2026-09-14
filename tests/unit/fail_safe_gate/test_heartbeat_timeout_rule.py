"""Unit tests for HeartbeatTimeoutRule."""

from src.modules.fail_safe_gate.domain.models import (
    EvaluationRequest,
    TelemetryData,
)
from src.modules.fail_safe_gate.domain.rules.heartbeat_timeout_rule import (
    HeartbeatTimeoutRule,
)


def _point(ts: int) -> TelemetryData:
    return TelemetryData(
        sensor_id="sensor-001",
        flow_rate=450.0,
        pressure=12.5,
        temperature=293.15,
        timestamp_ns=ts,
    )


def test_heartbeat_timeout_nominal() -> None:
    """[US-2][AC-2.2] Verify normal 100ms interval passes heartbeat check."""
    rule = HeartbeatTimeoutRule(max_interval_ms=250.0)
    assert rule.rule_id == "R-HEARTBEAT-04"

    # 100ms interval between previous and current
    prev = _point(1_000_000_000)
    curr = _point(1_100_000_000)

    req = EvaluationRequest(
        request_id="req-hb-1",
        regulator_id="reg-1",
        telemetry=curr,
        recent_history=(prev,),
    )
    decision = rule.evaluate(req)

    assert decision.is_allowed is True
    assert decision.status_code == 200
    assert decision.trip_required is False
    assert decision.violating_rule_id is None


def test_heartbeat_timeout_gap_exceeded() -> None:
    """[US-2][AC-2.2] Verify interval > 250ms trips heartbeat rule."""
    rule = HeartbeatTimeoutRule(max_interval_ms=250.0)

    # 300ms gap
    prev = _point(1_000_000_000)
    curr = _point(1_300_000_000)

    req = EvaluationRequest(
        request_id="req-hb-2",
        regulator_id="reg-1",
        telemetry=curr,
        recent_history=(prev,),
    )
    decision = rule.evaluate(req)

    assert decision.is_allowed is False
    assert decision.status_code == 422
    assert decision.trip_required is True
    assert decision.rule_id == "R-HEARTBEAT-04"
    assert decision.violating_rule_id == "R-HEARTBEAT-04"
    assert "Heartbeat timeout" in decision.reason
    assert decision.diagnostics is not None
    assert decision.diagnostics["interval_ms"] == 300.0


def test_heartbeat_timeout_no_history() -> None:
    """[US-2][AC-2.2] Verify first sample with no prior history passes."""
    rule = HeartbeatTimeoutRule(max_interval_ms=250.0)

    req = EvaluationRequest(
        request_id="req-hb-3",
        regulator_id="reg-1",
        telemetry=_point(1_000_000_000),
        recent_history=(),
    )
    decision = rule.evaluate(req)
    assert decision.is_allowed is True
    assert decision.status_code == 200
