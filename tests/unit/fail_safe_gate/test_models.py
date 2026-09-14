"""Unit tests for fail-safe gate domain models and exceptions."""

import pytest

from src.modules.fail_safe_gate.domain.exceptions import (
    ActuationInterlockConflict,
    CorrelationDriftViolation,
    FailSafeGateError,
    HardwareCommunicationError,
    InternalServiceError,
    InvalidPayloadError,
    SafetyEnvelopeViolation,
    SensorFreezeDetected,
)
from src.modules.fail_safe_gate.domain.models import (
    ActuatorCommand,
    ActuatorResult,
    AdversarialScenario,
    Decision,
    EvaluationRequest,
    GateStatus,
    ScenarioResult,
    TelemetryData,
)


def test_telemetry_data_instantiation() -> None:
    """[US-1][AC-1.2] Verify TelemetryData model fields and immutability."""
    telemetry = TelemetryData(
        sensor_id="sensor-001",
        flow_rate=450.0,
        pressure=12.5,
        temperature=293.15,
        timestamp_ns=1_700_000_000_000_000_000,
    )
    assert telemetry.sensor_id == "sensor-001"
    assert telemetry.flow_rate == 450.0
    assert telemetry.pressure == 12.5
    assert telemetry.temperature == 293.15
    assert telemetry.timestamp_ns == 1_700_000_000_000_000_000

    with pytest.raises(AttributeError):
        # Immutable / frozen dataclass check
        telemetry.flow_rate = 500.0  # type: ignore[misc]


def test_evaluation_request_instantiation() -> None:
    """[US-1][AC-1.2] Verify EvaluationRequest model defaults and structure."""
    telemetry = TelemetryData(
        sensor_id="sensor-001",
        flow_rate=450.0,
        pressure=12.5,
        temperature=293.15,
        timestamp_ns=1_700_000_000_000_000_000,
    )
    request = EvaluationRequest(
        request_id="req-123",
        regulator_id="reg-alpha",
        telemetry=telemetry,
    )
    assert request.request_id == "req-123"
    assert request.regulator_id == "reg-alpha"
    assert request.telemetry == telemetry
    assert request.recent_history == ()
    assert request.operating_mode == "normal"


def test_decision_instantiation() -> None:
    """[US-1][AC-1.2] Verify Decision model properties."""
    decision = Decision(
        is_allowed=True,
        status_code=200,
        rule_id="PASS",
        reason="Passed all checks",
        trip_required=False,
        violating_rule_id=None,
        diagnostics={"delta": 0.0},
    )
    assert decision.is_allowed is True
    assert decision.status_code == 200
    assert decision.rule_id == "PASS"
    assert decision.violating_rule_id == None
    assert decision.diagnostics == {"delta": 0.0}


def test_actuator_command_and_result() -> None:
    """[US-2][AC-2.1] Verify ActuatorCommand and ActuatorResult models."""
    command = ActuatorCommand(
        command_id="cmd-001",
        regulator_id="reg-alpha",
        target_state="closed",
        reason="Emergency close requested",
        initiated_by="test-agent",
        timeout_ms=50,
    )
    assert command.target_state == "closed"
    assert command.timeout_ms == 50

    result = ActuatorResult(
        command_id="cmd-001",
        regulator_id="reg-alpha",
        executed_state="closed",
        actuation_latency_ms=12.5,
        success=True,
        message="Closed successfully",
    )
    assert result.success is True
    assert result.actuation_latency_ms == 12.5


def test_adversarial_scenario_and_result() -> None:
    """[US-3][AC-3.2] Verify AdversarialScenario and ScenarioResult models."""
    scenario = AdversarialScenario(
        scenario_id="scen-001",
        anomaly_type="flow_spike",
        duration_ms=100,
        injection_magnitude=1500.0,
    )
    assert scenario.scenario_id == "scen-001"
    assert scenario.anomaly_type == "flow_spike"

    result = ScenarioResult(
        scenario_id="scen-001",
        passed=True,
        reaction_latency_ms=25.0,
        entered_safe_state=True,
        failure_reason=None,
    )
    assert result.passed is True
    assert result.reaction_latency_ms == 25.0


def test_gate_status_model() -> None:
    """[US-5][AC-5.2] Verify GateStatus model."""
    status = GateStatus(
        regulator_id="reg-alpha",
        valve_state="open",
        operational_mode="normal",
        offline_buffer_used_bytes=1024,
        offline_buffer_capacity_bytes=2147483648,
        last_heartbeat_timestamp_ns=1_700_000_000_000_000_000,
        last_trip_reason="Manual test",
        last_trip_timestamp_ns=1_699_999_000_000_000_000,
    )
    assert status.regulator_id == "reg-alpha"
    assert status.valve_state == "open"
    assert status.offline_buffer_capacity_bytes == 2147483648


def test_domain_exceptions_hierarchy() -> None:
    """[US-1][AC-1.2] Verify exception hierarchy and attributes."""
    assert issubclass(InvalidPayloadError, FailSafeGateError)
    assert issubclass(SafetyEnvelopeViolation, FailSafeGateError)
    assert issubclass(CorrelationDriftViolation, FailSafeGateError)
    assert issubclass(SensorFreezeDetected, FailSafeGateError)
    assert issubclass(ActuationInterlockConflict, FailSafeGateError)
    assert issubclass(HardwareCommunicationError, FailSafeGateError)
    assert issubclass(InternalServiceError, FailSafeGateError)

    e1 = SafetyEnvelopeViolation("Flow exceeded limit", details={"flow_rate": 1500.0})
    assert str(e1) == "Flow exceeded limit"
    assert e1.code == "ENVELOPE_TRIP"
    assert e1.status_code == 422
    assert e1.details == {"flow_rate": 1500.0}

    e2 = CorrelationDriftViolation("Correlation drift", details={"residual": 12.0})
    assert e2.code == "CORRELATION_DRIFT"
    assert e2.status_code == 422

    e3 = SensorFreezeDetected("Sensor frozen", details={"samples": 5})
    assert e3.code == "SENSOR_FROZEN"
    assert e3.status_code == 422

    e4 = InternalServiceError("Internal service error", details={"cause": "runtime"})
    assert e4.code == "INTERNAL_ERROR"
    assert e4.status_code == 500
