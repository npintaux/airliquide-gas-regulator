"""Canonical Contract Verification Test Suite for fail_safe_gate.

Validates that subsystem HTTP entrypoints strictly adhere to the frozen openapi.yaml
interface contract, including HTTP status codes, response schemas, error structures,
and routing versioning conventions.

Authored by: Independent Test Architect (/test-architect)
Subsystem: fail_safe_gate
Black-box Isolation: Imports ONLY public entrypoints (src.modules.fail_safe_gate.entrypoints.api).
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

FROZEN_CONTRACT = Path("src/modules/fail_safe_gate/openapi.yaml")


class TestContractFailSafeGate:
    """Black-box contract compliance test suite for fail_safe_gate."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Instantiate test client for the fail_safe_gate public entrypoint."""
        from src.modules.fail_safe_gate.entrypoints.api import app

        return TestClient(app)

    @pytest.fixture
    def frozen_contract(self) -> Mapping[str, Any]:
        """Load the frozen openapi.yaml the running app must satisfy."""
        return yaml.safe_load(FROZEN_CONTRACT.read_text(encoding="utf-8"))

    def test_live_app_conforms_to_frozen_contract(
        self, client: TestClient, frozen_contract: Mapping[str, Any]
    ) -> None:
        """Verify every path, method, and response status code in openapi.yaml is served."""
        live: Mapping[str, Any] = client.get("/openapi.json").json()
        live_paths: Mapping[str, Any] = live.get("paths", {})

        for path, frozen_ops in frozen_contract.get("paths", {}).items():
            assert path in live_paths, f"Frozen contract path '{path}' is not served by the app."
            for method, frozen_op in frozen_ops.items():
                op = f"{method.upper()} {path}"
                live_op = live_paths[path].get(method)
                assert live_op is not None, f"Frozen operation '{op}' is missing."
                live_codes = {str(c) for c in live_op.get("responses", {})}
                for status_code in frozen_op.get("responses", {}):
                    assert str(status_code) in live_codes, (
                        f"Frozen status '{status_code}' for '{op}' is not served."
                    )

    def test_openapi_spec_route_versioning(self, frozen_contract: Mapping[str, Any]) -> None:
        """Verify that all exposed paths are versioned with /v<N>/ prefix."""
        paths = frozen_contract.get("paths", {})
        assert len(paths) > 0, "No paths defined in openapi.yaml"
        for path in paths:
            assert path.startswith("/v"), f"Path '{path}' violates /v<N>/ versioning contract."

    # --- /v1/gate/evaluate Contract Tests ---

    def test_contract_evaluate_success_200(self, client: TestClient) -> None:
        """Assert evaluate endpoint returns 200 and conforms to EvaluationResponse schema."""
        payload = {
            "request_id": "req-contract-200",
            "regulator_id": "REG-001",
            "telemetry": {
                "sensor_id": "SENSOR-01",
                "flow_rate": 150.0,
                "pressure": 5.0,
                "temperature": 293.15,
                "timestamp_ns": 1726309320000000000,
            },
            "recent_history": [],
            "operating_mode": "normal",
        }
        response = client.post("/v1/gate/evaluate", json=payload)
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert data["request_id"] == "req-contract-200"
        assert data["regulator_id"] == "REG-001"
        assert "is_allowed" in data
        assert "status_code" in data
        assert "decision_summary" in data
        assert "trip_required" in data

    def test_contract_evaluate_bad_request_400(self, client: TestClient) -> None:
        """Assert evaluate endpoint returns 400 Bad Request on malformed payload."""
        malformed_payload = {
            "request_id": "req-invalid",
            # missing regulator_id and telemetry
        }
        response = client.post("/v1/gate/evaluate", json=malformed_payload)
        assert response.status_code == 400
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_contract_evaluate_trip_rule_violation_422(self, client: TestClient) -> None:
        """Assert evaluate endpoint returns 422 Unprocessable when safety envelope is violated."""
        violating_payload = {
            "request_id": "req-contract-422",
            "regulator_id": "REG-001",
            "telemetry": {
                "sensor_id": "SENSOR-01",
                "flow_rate": 9999.0,  # critical out-of-bounds pressure/flow
                "pressure": 999.0,
                "temperature": 1500.0,
                "timestamp_ns": 1726309320000000000,
            },
            "recent_history": [],
            "operating_mode": "normal",
        }
        response = client.post("/v1/gate/evaluate", json=violating_payload)
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert data["request_id"] == "req-contract-422"
        assert data["is_allowed"] is False
        assert data["trip_required"] is True

    def test_contract_evaluate_internal_error_500(self, client: TestClient) -> None:
        """Assert evaluate endpoint returns 500 on internal fault without leaking stack traces."""
        fault_payload = {
            "request_id": "trigger-fault-500",
            "regulator_id": "REG-FAULT-500",
            "telemetry": {
                "sensor_id": "SENSOR-FAULT",
                "flow_rate": 100.0,
                "pressure": 5.0,
                "temperature": 293.15,
                "timestamp_ns": 1726309320000000000,
            },
            "recent_history": [],
            "operating_mode": "normal",
        }
        response = client.post("/v1/gate/evaluate", json=fault_payload)
        assert response.status_code == 500
        assert "Traceback" not in response.text
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    # --- /v1/gate/close Contract Tests ---

    def test_contract_close_success_200(self, client: TestClient) -> None:
        """Assert close endpoint returns 200 and conforms to CloseGateResponse schema."""
        payload = {
            "command_id": "cmd-close-001",
            "regulator_id": "REG-001",
            "target_state": "closed",
            "reason": "Routine scheduled safety shutdown",
            "initiated_by": "operator-override",
            "timeout_ms": 50,
        }
        response = client.post("/v1/gate/close", json=payload)
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert data["command_id"] == "cmd-close-001"
        assert data["regulator_id"] == "REG-001"
        assert data["executed_state"] in ["closed", "safe_hold", "minimum_safe_flow", "physical_bypass"]
        assert "actuation_latency_ms" in data
        assert "success" in data

    def test_contract_close_bad_request_400(self, client: TestClient) -> None:
        """Assert close endpoint returns 400 Bad Request on invalid parameters."""
        response = client.post("/v1/gate/close", json={"command_id": "missing-fields"})
        assert response.status_code == 400
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_contract_close_interlock_conflict_422(self, client: TestClient) -> None:
        """Assert close endpoint returns 422 when actuation rejected due to hardware conflict."""
        payload = {
            "command_id": "cmd-conflict-422",
            "regulator_id": "REG-INTERLOCKED",
            "target_state": "closed",
            "reason": "Test conflict with hardware lockout",
            "initiated_by": "automated-fail-safe",
            "timeout_ms": 50,
        }
        response = client.post("/v1/gate/close", json=payload)
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_contract_close_actuator_driver_failure_500(self, client: TestClient) -> None:
        """Assert close endpoint returns 500 when hardware communication or driver fails."""
        payload = {
            "command_id": "cmd-driver-fail-500",
            "regulator_id": "REG-BROKEN-ACTUATOR",
            "target_state": "closed",
            "reason": "Simulate actuator bus timeout",
            "initiated_by": "automated-fail-safe",
            "timeout_ms": 50,
        }
        response = client.post("/v1/gate/close", json=payload)
        assert response.status_code == 500
        assert "Traceback" not in response.text
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    # --- /v1/gate/simulate Contract Tests ---

    def test_contract_simulate_success_200(self, client: TestClient) -> None:
        """Assert simulate endpoint returns 200 with AdversarialSimulationResponse schema."""
        payload = {
            "simulation_id": "sim-pr-101",
            "candidate_version": "git-sha-abc1234",
            "scenarios": [
                {
                    "scenario_id": "scen-flow-01",
                    "anomaly_type": "flow_spike",
                    "duration_ms": 40,
                    "injection_magnitude": 2.5,
                }
            ],
            "max_response_window_ms": 50,
        }
        response = client.post("/v1/gate/simulate", json=payload)
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert data["simulation_id"] == "sim-pr-101"
        assert data["candidate_version"] == "git-sha-abc1234"
        assert data["overall_verdict"] in ["passed", "rejected"]
        assert "scenarios_passed" in data
        assert "scenarios_total" in data
        assert "results" in data

    def test_contract_simulate_bad_request_400(self, client: TestClient) -> None:
        """Assert simulate endpoint returns 400 Bad Request on invalid scenario definition."""
        response = client.post("/v1/gate/simulate", json={"simulation_id": "invalid-no-scenarios"})
        assert response.status_code == 400
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_contract_simulate_adversarial_failure_422(self, client: TestClient) -> None:
        """Assert simulate endpoint returns 422 when candidate logic fails safety checks."""
        payload = {
            "simulation_id": "sim-fail-422",
            "candidate_version": "git-sha-unsafe-algo",
            "scenarios": [
                {
                    "scenario_id": "scen-vacuum-01",
                    "anomaly_type": "vacuum_drop",
                    "duration_ms": 100,
                    "injection_magnitude": 10.0,
                }
            ],
            "max_response_window_ms": 50,
        }
        response = client.post("/v1/gate/simulate", json=payload)
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert data["overall_verdict"] == "rejected"

    def test_contract_simulate_runner_error_500(self, client: TestClient) -> None:
        """Assert simulate endpoint returns 500 when simulation runner encounters an execution error."""
        payload = {
            "simulation_id": "sim-runner-err-500",
            "candidate_version": "git-sha-crash-runner",
            "scenarios": [
                {
                    "scenario_id": "scen-crash",
                    "anomaly_type": "noisy_turbulence",
                    "duration_ms": 50,
                    "injection_magnitude": 1.0,
                }
            ],
        }
        response = client.post("/v1/gate/simulate", json=payload)
        assert response.status_code == 500
        assert "Traceback" not in response.text
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    # --- /v1/gate/status Contract Tests ---

    def test_contract_status_success_200(self, client: TestClient) -> None:
        """Assert status endpoint returns 200 with GateStatusResponse schema."""
        response = client.get("/v1/gate/status?regulator_id=REG-001")
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert data["regulator_id"] == "REG-001"
        assert "valve_state" in data
        assert "operational_mode" in data
        assert "offline_buffer_used_bytes" in data
        assert "offline_buffer_capacity_bytes" in data
        assert "last_heartbeat_timestamp_ns" in data

    def test_contract_status_bad_request_400(self, client: TestClient) -> None:
        """Assert status endpoint returns 400 Bad Request on malformed query parameters."""
        response = client.get("/v1/gate/status?regulator_id=" + "X" * 1000)
        assert response.status_code == 400
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_contract_status_unprocessable_422(self, client: TestClient) -> None:
        """Assert status endpoint returns 422 when regulator state is unprocessable."""
        response = client.get("/v1/gate/status?regulator_id=REG-UNCONFIGURED")
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data

    def test_contract_status_internal_error_500(self, client: TestClient) -> None:
        """Assert status endpoint returns 500 when telemetry status backend fails."""
        response = client.get("/v1/gate/status?regulator_id=REG-BACKEND-CRASH")
        assert response.status_code == 500
        assert "Traceback" not in response.text
        data: Mapping[str, Any] = response.json()
        assert "code" in data
        assert "message" in data
