"""Integration and API unit tests for fail-safe gate entrypoints."""

import pytest
from fastapi.testclient import TestClient

from src.modules.fail_safe_gate.entrypoints.api import (
    app,
    get_actuator,
    get_engine,
    get_simulation_runner,
)


@pytest.fixture
def client() -> TestClient:
    """Create test client for the FastAPI entrypoint."""
    return TestClient(app, raise_server_exceptions=False)


def test_dependency_accessors() -> None:
    """[US-1][AC-1.2] Verify dependency getters return proper instances."""
    actuator = get_actuator()
    engine = get_engine()
    runner = get_simulation_runner()
    assert actuator is not None
    assert engine is not None
    assert runner is not None


def test_evaluate_nominal_success(client: TestClient) -> None:
    """[US-1][AC-1.2] POST /v1/gate/evaluate nominal telemetry returns 200."""
    payload = {
        "request_id": "req-001",
        "regulator_id": "reg-alpha",
        "telemetry": {
            "sensor_id": "sensor-1",
            "flow_rate": 450.0,
            "pressure": 12.5,
            "temperature": 293.15,
            "timestamp_ns": 1_700_000_000_000_000_000,
        },
    }
    response = client.post("/v1/gate/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["request_id"] == "req-001"
    assert data["regulator_id"] == "reg-alpha"
    assert data["is_allowed"] is True
    assert data["status_code"] == 200
    assert data["trip_required"] is False
    assert data["violating_rule_id"] is None


def test_evaluate_envelope_trip_returns_422(client: TestClient) -> None:
    """[US-1][AC-1.2] POST /v1/gate/evaluate out-of-range flow returns 422."""
    payload = {
        "request_id": "req-002",
        "regulator_id": "reg-alpha",
        "telemetry": {
            "sensor_id": "sensor-1",
            "flow_rate": 1500.0,
            "pressure": 12.5,
            "temperature": 293.15,
            "timestamp_ns": 1_700_000_000_000_000_000,
        },
    }
    response = client.post("/v1/gate/evaluate", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["is_allowed"] is False
    assert data["status_code"] == 422
    assert data["trip_required"] is True
    assert data["violating_rule_id"] == "R-STATIC-01"


def test_evaluate_correlation_drift_returns_422(client: TestClient) -> None:
    """[US-1][AC-1.3] POST /v1/gate/evaluate drift returns 422."""
    payload = {
        "request_id": "req-003",
        "regulator_id": "reg-alpha",
        "telemetry": {
            "sensor_id": "sensor-1",
            "flow_rate": 650.0,  # drifted from expected 450.0
            "pressure": 12.5,
            "temperature": 293.15,
            "timestamp_ns": 1_700_000_000_000_000_000,
        },
    }
    response = client.post("/v1/gate/evaluate", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["is_allowed"] is False
    assert data["violating_rule_id"] == "R-CORR-02"


def test_evaluate_sensor_freeze_returns_422(client: TestClient) -> None:
    """[US-2][AC-2.2] POST /v1/gate/evaluate frozen telemetry returns 422."""
    history = [
        {
            "sensor_id": "sensor-1",
            "flow_rate": 450.0,
            "pressure": 12.5,
            "temperature": 293.15,
            "timestamp_ns": 1_000_000_000 + i * 100_000_000,
        }
        for i in range(5)
    ]
    payload = {
        "request_id": "req-004",
        "regulator_id": "reg-alpha",
        "telemetry": {
            "sensor_id": "sensor-1",
            "flow_rate": 450.0,
            "pressure": 12.5,
            "temperature": 293.15,
            "timestamp_ns": 1_600_000_000,
        },
        "recent_history": history,
    }
    response = client.post("/v1/gate/evaluate", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["is_allowed"] is False
    assert data["violating_rule_id"] == "R-VAR-03"


def test_evaluate_invalid_payload_returns_400(client: TestClient) -> None:
    """[US-1][AC-1.2] POST /v1/gate/evaluate with invalid fields returns 400."""
    payload = {
        "request_id": "req-bad",
        "regulator_id": "reg-alpha",
        "telemetry": {
            "sensor_id": "sensor-1",
            "flow_rate": 450.0,
            "pressure": -5.0,  # Negative pressure is invalid
            "temperature": 293.15,
            "timestamp_ns": 1_000,
        },
    }
    response = client.post("/v1/gate/evaluate", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["code"] == "INVALID_PAYLOAD"


def test_evaluate_missing_telemetry_returns_400(client: TestClient) -> None:
    """[US-1][AC-1.2] POST /v1/gate/evaluate missing telemetry returns 400."""
    response = client.post(
        "/v1/gate/evaluate",
        json={"request_id": "r1", "regulator_id": "reg1"},
    )
    assert response.status_code == 400


def test_close_gate_success(client: TestClient) -> None:
    """[US-2][AC-2.1] POST /v1/gate/close dispatches actuation and returns 200."""
    payload = {
        "command_id": "cmd-c1",
        "regulator_id": "reg-alpha",
        "target_state": "closed",
        "reason": "Emergency shutoff test",
        "initiated_by": "test-suite",
        "timeout_ms": 50,
    }
    response = client.post("/v1/gate/close", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["command_id"] == "cmd-c1"
    assert data["executed_state"] == "closed"
    assert data["actuation_latency_ms"] <= 50.0
    assert data["success"] is True


def test_close_gate_invalid_payload_returns_400(client: TestClient) -> None:
    """[US-2][AC-2.1] POST /v1/gate/close with unknown target state returns 400."""
    payload = {
        "command_id": "cmd-bad",
        "regulator_id": "reg-alpha",
        "target_state": "non_existent_state",
        "reason": "Bad command test",
        "initiated_by": "test-suite",
    }
    response = client.post("/v1/gate/close", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["code"] == "INVALID_PAYLOAD"


def test_close_gate_interlock_conflict_returns_422(client: TestClient) -> None:
    """[US-2][AC-2.1] POST /v1/gate/close when interlock conflicts returns 422."""
    actuator = get_actuator()
    actuator._locked_states.add("physical_bypass")
    try:
        payload = {
            "command_id": "cmd-interlock",
            "regulator_id": "reg-alpha",
            "target_state": "physical_bypass",
            "reason": "Test locked state",
            "initiated_by": "test-suite",
        }
        response = client.post("/v1/gate/close", json=payload)
        assert response.status_code == 422
        data = response.json()
        assert data["code"] == "INTERLOCK_CONFLICT"
    finally:
        actuator._locked_states.discard("physical_bypass")


def test_close_gate_comm_error_returns_500(client: TestClient) -> None:
    """[US-2][AC-2.1] POST /v1/gate/close with hardware comm error returns 500."""
    actuator = get_actuator()
    actuator._fail_communication = True
    try:
        payload = {
            "command_id": "cmd-err",
            "regulator_id": "reg-alpha",
            "target_state": "closed",
            "reason": "Test comm failure",
            "initiated_by": "test-suite",
        }
        response = client.post("/v1/gate/close", json=payload)
        assert response.status_code == 500
        data = response.json()
        assert data["code"] == "ACTUATOR_COMM_ERROR"
    finally:
        actuator._fail_communication = False


def test_simulate_adversarial_success(client: TestClient) -> None:
    """[US-3][AC-3.2] POST /v1/gate/simulate runs scenario suite and returns 200."""
    payload = {
        "simulation_id": "sim-test-01",
        "candidate_version": "v1.0.0-rc1",
        "scenarios": [
            {
                "scenario_id": "s-spike",
                "anomaly_type": "flow_spike",
                "duration_ms": 100,
                "injection_magnitude": 1500.0,
            },
            {
                "scenario_id": "s-freeze",
                "anomaly_type": "frozen_sensor",
                "duration_ms": 100,
                "injection_magnitude": 0.0,
            },
        ],
        "max_response_window_ms": 50,
    }
    response = client.post("/v1/gate/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["simulation_id"] == "sim-test-01"
    assert data["overall_verdict"] == "passed"
    assert data["scenarios_passed"] == 2
    assert data["scenarios_total"] == 2


def test_simulate_adversarial_rejected_returns_422(client: TestClient) -> None:
    """[US-3][AC-3.3] POST /v1/gate/simulate returns 422 if overall verdict is rejected."""
    payload = {
        "simulation_id": "sim-test-02",
        "candidate_version": "v1.0.0-bad",
        "scenarios": [
            {
                "scenario_id": "s-unknown",
                "anomaly_type": "unknown_anomaly_type",
                "duration_ms": 50,
                "injection_magnitude": 0.0,
            }
        ],
    }
    response = client.post("/v1/gate/simulate", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["overall_verdict"] == "rejected"


def test_simulate_adversarial_invalid_returns_400(client: TestClient) -> None:
    """[US-3][AC-3.2] POST /v1/gate/simulate with empty scenarios returns 400."""
    payload = {
        "simulation_id": "sim-bad",
        "candidate_version": "v1.0.0",
        "scenarios": [],
    }
    response = client.post("/v1/gate/simulate", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert data["code"] == "INVALID_PAYLOAD"


def test_get_gate_status(client: TestClient) -> None:
    """[US-5][AC-5.2] GET /v1/gate/status returns live status snapshot."""
    response = client.get("/v1/gate/status?regulator_id=reg-test-01")
    assert response.status_code == 200
    data = response.json()
    assert data["regulator_id"] == "reg-test-01"
    assert "valve_state" in data
    assert "operational_mode" in data
    assert "offline_buffer_used_bytes" in data
    assert "offline_buffer_capacity_bytes" in data
    assert "last_heartbeat_timestamp_ns" in data


def test_get_gate_status_default_regulator(client: TestClient) -> None:
    """[US-5][AC-5.2] GET /v1/gate/status without query param defaults to default regulator."""
    response = client.get("/v1/gate/status")
    assert response.status_code == 200
    data = response.json()
    assert data["regulator_id"] == "default-regulator"


def test_evaluate_simulated_fault_returns_500(client: TestClient) -> None:
    """[US-1][AC-1.1] POST /v1/gate/evaluate returns 500 when regulator_id indicates fault."""
    payload = {
        "request_id": "req-fault-1",
        "regulator_id": "REG-FAULT-500",
        "telemetry": {
            "sensor_id": "s-01",
            "flow_rate": 100.0,
            "pressure": 5.0,
            "temperature": 293.15,
            "timestamp_ns": 1_000_000_000,
        },
    }
    response = client.post("/v1/gate/evaluate", json=payload)
    assert response.status_code == 500
    data = response.json()
    assert data["code"] == "INTERNAL_ERROR"


def test_get_gate_status_unconfigured_returns_422(client: TestClient) -> None:
    """[US-5][AC-5.2] GET /v1/gate/status with unconfigured regulator returns 422."""
    response = client.get("/v1/gate/status?regulator_id=REG-UNCONFIGURED")
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "UNCONFIGURED_REGULATOR"


def test_get_gate_status_backend_crash_returns_500(client: TestClient) -> None:
    """[US-5][AC-5.2] GET /v1/gate/status with crashing regulator returns 500."""
    response = client.get("/v1/gate/status?regulator_id=REG-CRASH")
    assert response.status_code == 500
    data = response.json()
    assert data["code"] == "INTERNAL_ERROR"
