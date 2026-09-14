"""Canonical Behavioral Verification Test Suite for fail_safe_gate.

Tests end-to-end user stories and acceptance criteria defined in docs/PRD.md and
mapped to fail_safe_gate in docs/traceability.md:
- US-1: Real-Time Telemetry Ingestion & Safety Envelope Validation (AC-1.2, AC-1.3)
- US-2: Hardware Fail-Safe Interrupt Trigger (AC-2.1, AC-2.2, AC-2.3)
- US-3: Automated Adversarial Quality Gate for CI/CD Pipelines (AC-3.1, AC-3.2, AC-3.3)
- US-5: Edge-Safe Offline Fallback Mode (AC-5.1, AC-5.2, AC-5.3)

Authored by: Independent Test Architect (/test-architect)
Subsystem: fail_safe_gate
Black-box Isolation: Imports ONLY public entrypoints (src.modules.fail_safe_gate.entrypoints.api).
"""

from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient


class TestBehavioralFailSafeGate:
    """End-to-end user story and acceptance criteria verification for fail_safe_gate."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Instantiate test client for fail_safe_gate public entrypoint."""
        from src.modules.fail_safe_gate.entrypoints.api import app

        return TestClient(app)

    # --- User Story US-1: Real-Time Telemetry Ingestion & Safety Envelope Validation ---

    def test_us1_ac1_1_valid_telemetry_passes_envelope_validation(
        self, client: TestClient
    ) -> None:
        """[US-1][AC-1.1] Ingested telemetry within safe bounds evaluates with 200 is_allowed=True."""
        payload = {
            "request_id": "req-us1-valid-01",
            "regulator_id": "REG-ZONE-1",
            "telemetry": {
                "sensor_id": "FLOW-01",
                "flow_rate": 100.0,
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
        assert data["is_allowed"] is True
        assert data["trip_required"] is False
        assert data["regulator_id"] == "REG-ZONE-1"

    def test_us1_ac1_2_out_of_bounds_flow_rejected_with_safety_trip(
        self, client: TestClient
    ) -> None:
        """[US-1][AC-1.2] Out-of-range flow rate telemetry triggers envelope trip (422) and mandates close."""
        payload = {
            "request_id": "req-us1-invalid-flow",
            "regulator_id": "REG-ZONE-1",
            "telemetry": {
                "sensor_id": "FLOW-01",
                "flow_rate": 5000.0,  # Exceeds max allowable flow envelope
                "pressure": 5.0,
                "temperature": 293.15,
                "timestamp_ns": 1726309320000000000,
            },
            "recent_history": [],
            "operating_mode": "normal",
        }
        response = client.post("/v1/gate/evaluate", json=payload)
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert data["is_allowed"] is False
        assert data["trip_required"] is True
        assert "violating_rule_id" in data
        assert data["violating_rule_id"] is not None

    def test_us1_ac1_3_sensor_drift_detected_via_pressure_temperature_correlation(
        self, client: TestClient
    ) -> None:
        """[US-1][AC-1.3] Dynamic correlation violation (sensor drift between P and T) triggers trip."""
        payload = {
            "request_id": "req-us1-drift-detected",
            "regulator_id": "REG-ZONE-1",
            "telemetry": {
                "sensor_id": "FLOW-01",
                "flow_rate": 100.0,
                "pressure": 0.5,  # Incompatible near-vacuum pressure for high temperature and normal flow
                "temperature": 450.0,
                "timestamp_ns": 1726309320000000000,
            },
            "recent_history": [],
            "operating_mode": "normal",
        }
        response = client.post("/v1/gate/evaluate", json=payload)
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert data["is_allowed"] is False
        assert data["trip_required"] is True
        assert "diagnostics" in data

    # --- User Story US-2: Hardware Fail-Safe Interrupt Trigger ---

    def test_us2_ac2_1_sub_50ms_hardware_close_gate_dispatch(
        self, client: TestClient
    ) -> None:
        """[US-2][AC-2.1] Issues a hardware Close-Gate command within 50ms upon critical violation."""
        payload = {
            "command_id": "cmd-us2-close-01",
            "regulator_id": "REG-MAIN-VALVE",
            "target_state": "closed",
            "reason": "Critical pressure surge detected",
            "initiated_by": "automated-fail-safe",
            "timeout_ms": 50,
        }
        response = client.post("/v1/gate/close", json=payload)
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert data["success"] is True
        assert data["executed_state"] == "closed"
        assert data["actuation_latency_ms"] <= 50.0

    def test_us2_ac2_2_frozen_sensor_lack_of_variance_triggers_trip(
        self, client: TestClient
    ) -> None:
        """[US-2][AC-2.2] Detects frozen telemetry (zero variance in recent sliding window) and trips gate."""
        history = [
            {
                "sensor_id": "FLOW-01",
                "flow_rate": 100.000,
                "pressure": 5.000,
                "temperature": 293.15,
                "timestamp_ns": 1726309320000000000 + i * 100_000_000,
            }
            for i in range(10)
        ]
        payload = {
            "request_id": "req-us2-frozen-sensor",
            "regulator_id": "REG-ZONE-1",
            "telemetry": {
                "sensor_id": "FLOW-01",
                "flow_rate": 100.000,
                "pressure": 5.000,
                "temperature": 293.15,
                "timestamp_ns": 1726309321100000000,
            },
            "recent_history": history,
            "operating_mode": "normal",
        }
        response = client.post("/v1/gate/evaluate", json=payload)
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert data["is_allowed"] is False
        assert data["trip_required"] is True

    def test_us2_ac2_3_engage_minimum_safe_flow_on_primary_sensor_dropout(
        self, client: TestClient
    ) -> None:
        """[US-2][AC-2.3] Automatically engages minimum-safe-flow position when sensor stream fails."""
        payload = {
            "command_id": "cmd-us2-dropout-safe-hold",
            "regulator_id": "REG-BACKUP-LINE",
            "target_state": "minimum_safe_flow",
            "reason": "Missing sensor heartbeat dropout",
            "initiated_by": "automated-fail-safe",
            "timeout_ms": 50,
        }
        response = client.post("/v1/gate/close", json=payload)
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert data["success"] is True
        assert data["executed_state"] == "minimum_safe_flow"

    # --- User Story US-3: Automated Adversarial Quality Gate for CI/CD Pipelines ---

    def test_us3_ac3_1_adversarial_simulation_passing_candidate_logic(
        self, client: TestClient
    ) -> None:
        """[US-3][AC-3.1] Executes synthetic anomalies and passes PR gate when candidate safely trips."""
        payload = {
            "simulation_id": "sim-pr-305",
            "candidate_version": "v1.2.0-rc1",
            "scenarios": [
                {
                    "scenario_id": "scen-spike",
                    "anomaly_type": "flow_spike",
                    "duration_ms": 30,
                    "injection_magnitude": 3.0,
                },
                {
                    "scenario_id": "scen-vacuum",
                    "anomaly_type": "vacuum_drop",
                    "duration_ms": 40,
                    "injection_magnitude": 0.2,
                },
            ],
            "max_response_window_ms": 50,
        }
        response = client.post("/v1/gate/simulate", json=payload)
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert data["overall_verdict"] == "passed"
        assert data["scenarios_passed"] == 2
        assert data["scenarios_total"] == 2

    def test_us3_ac3_2_adversarial_simulation_blocks_pr_on_safety_regression(
        self, client: TestClient
    ) -> None:
        """[US-3][AC-3.2] Blocks PR and returns 422 rejected verdict when candidate fails latency budget."""
        payload = {
            "simulation_id": "sim-pr-unsafe-candidate",
            "candidate_version": "v1.2.0-flawed",
            "scenarios": [
                {
                    "scenario_id": "scen-turbulence",
                    "anomaly_type": "noisy_turbulence",
                    "duration_ms": 100,
                    "injection_magnitude": 8.5,
                }
            ],
            "max_response_window_ms": 50,
        }
        response = client.post("/v1/gate/simulate", json=payload)
        assert response.status_code == 422
        data: Mapping[str, Any] = response.json()
        assert data["overall_verdict"] == "rejected"
        assert data["scenarios_passed"] < data["scenarios_total"]

    # --- User Story US-5: Edge-Safe Offline Fallback Mode ---

    def test_us5_ac5_1_evaluate_under_offline_fallback_mode_uses_cached_policy(
        self, client: TestClient
    ) -> None:
        """[US-5][AC-5.1] Evaluates telemetry safely using edge-cached policy during WAN disconnect."""
        payload = {
            "request_id": "req-us5-offline-01",
            "regulator_id": "REG-EDGE-01",
            "telemetry": {
                "sensor_id": "FLOW-EDGE-01",
                "flow_rate": 80.0,
                "pressure": 4.0,
                "temperature": 290.0,
                "timestamp_ns": 1726309320000000000,
            },
            "recent_history": [],
            "operating_mode": "offline_fallback",
        }
        response = client.post("/v1/gate/evaluate", json=payload)
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert data["is_allowed"] is True
        assert data["trip_required"] is False

    def test_us5_ac5_2_status_reports_offline_buffer_utilization(
        self, client: TestClient
    ) -> None:
        """[US-5][AC-5.2] Gate status reports active offline buffer queued bytes during network loss."""
        response = client.get("/v1/gate/status?regulator_id=REG-EDGE-01")
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        assert "operational_mode" in data
        assert "offline_buffer_used_bytes" in data
        assert "offline_buffer_capacity_bytes" in data
        assert data["offline_buffer_capacity_bytes"] > 0
        assert data["offline_buffer_used_bytes"] <= data["offline_buffer_capacity_bytes"]
