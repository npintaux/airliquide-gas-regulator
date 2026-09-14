"""Canonical Behavioral Verification Test Suite for observability_dashboard.

Tests end-to-end user stories and acceptance criteria defined in docs/PRD.md and
mapped to observability_dashboard in docs/traceability.md.

Every test method maps directly to PRD User Story [US-4] and its Acceptance Criteria:
- [US-4][AC-4.1] Display real-time status of all active gas regulator gates and sensor streams.
- [US-4][AC-4.2] Show incident logs with automated root-cause summaries upon safety threshold trips or sensor dropouts.
- [US-4][AC-4.3] Route critical incident notifications to on-call engineers via integrated alert channels within 60 seconds.

Strict Black-Box Isolation: Imports ONLY from public entrypoints (api.app).
"""

from collections.abc import Mapping
from typing import Any

import pytest
from fastapi.testclient import TestClient


class TestObservabilityDashboardBehavioralAcceptance:
    """End-to-end user story and acceptance criteria verification for Observability Dashboard."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Instantiate test client for the subsystem public entrypoint."""
        from src.modules.observability_dashboard.entrypoints.api import app

        return TestClient(app)

    # --- User Story US-4: Real-Time Health & Incident Observability Dashboard ---

    def test_us4_ac4_1_real_time_flow_health_status_display(self, client: TestClient) -> None:
        """[US-4][AC-4.1] Display real-time status of all active gas regulator gates and sensor streams.

        Verifies that site operators can view active regulator counts, operational gate status
        (NORMAL_REGULATION, MINIMUM_SAFE_FLOW, FAIL_SAFE_HOLD, etc.), flow rates in sccm, pressure,
        temperature, and variance status across all monitored gates.
        """
        response = client.get("/v1/dashboard/health")
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()

        assert "status" in data
        assert data["status"] in ["HEALTHY", "DEGRADED", "CRITICAL"]
        assert "active_regulators_count" in data
        assert "gates" in data
        assert isinstance(data["gates"], list)

        # Validate gate operational state representation
        for gate in data["gates"]:
            assert "regulator_id" in gate
            assert "gate_status" in gate
            assert gate["gate_status"] in [
                "NORMAL_REGULATION",
                "MINIMUM_SAFE_FLOW",
                "FAIL_SAFE_HOLD",
                "CLOSE_GATE_LOCKED",
                "OFFLINE_FALLBACK",
            ]
            assert "current_flow_sccm" in gate
            assert isinstance(gate["current_flow_sccm"], (int, float))
            assert "current_pressure_psi" in gate
            assert isinstance(gate["current_pressure_psi"], (int, float))
            assert "current_temperature_c" in gate
            assert isinstance(gate["current_temperature_c"], (int, float))
            assert "variance_status" in gate
            assert gate["variance_status"] in ["NORMAL", "FROZEN_SUSPECTED", "ERRATIC"]
            assert "last_heartbeat" in gate

    def test_us4_ac4_1_filter_health_by_zone_and_regulator(self, client: TestClient) -> None:
        """[US-4][AC-4.1] Filter real-time health metrics by specific industrial zone or regulator.

        Verifies that filtering parameters allow Alexandre Morin (Operations Manager) to inspect
        a specific plant zone or single regulator gate during targeted diagnostics.
        """
        response = client.get("/v1/dashboard/health", params={"zone_id": "zone-a"})
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        for gate in data["gates"]:
            assert gate["zone_id"] == "zone-a"

    def test_us4_ac4_2_automated_incident_log_root_cause_summaries(
        self, client: TestClient
    ) -> None:
        """[US-4][AC-4.2] Show incident logs with automated root-cause summaries upon safety threshold trips or sensor dropouts.

        Verifies that incident records contain automated diagnostic root causes (e.g. pressure-flow
        divergence, frozen variance, vacuum drop), trip timestamps, severity categorization,
        and high-frequency pre-trip telemetry snapshot references for root-cause triage.
        """
        response = client.get("/v1/dashboard/incidents", params={"severity": "CRITICAL", "limit": 10})
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()

        assert "incidents" in data
        assert isinstance(data["incidents"], list)
        assert data["total_count"] >= len(data["incidents"])

        for incident in data["incidents"]:
            assert "incident_id" in incident
            assert "regulator_id" in incident
            assert incident["severity"] == "CRITICAL"
            assert "trip_reason" in incident
            assert len(incident["trip_reason"]) > 0
            # Root cause summary must be present and descriptive
            assert "root_cause_summary" in incident
            assert len(incident["root_cause_summary"]) > 0
            assert "triggered_at" in incident
            assert "status" in incident
            assert incident["status"] in ["OPEN", "ACKNOWLEDGED", "RESOLVED"]

    def test_us4_ac4_2_filter_incidents_by_regulator_id(self, client: TestClient) -> None:
        """[US-4][AC-4.2] Incident logs can be filtered by specific regulator ID for focused historical audit.

        Verifies targeted investigation of repeated fail-safe trip occurrences on an isolated valve.
        """
        target_regulator = "reg-line-4"
        response = client.get("/v1/dashboard/incidents", params={"regulator_id": target_regulator})
        assert response.status_code == 200
        data: Mapping[str, Any] = response.json()
        for incident in data["incidents"]:
            assert incident["regulator_id"] == target_regulator

    def test_us4_ac4_3_sub_60s_on_call_engineer_alert_routing(self, client: TestClient) -> None:
        """[US-4][AC-4.3] Route critical incident notifications to on-call engineers via integrated alert channels within 60 seconds.

        Verifies that dispatching a critical alert to PagerDuty or Cloud Monitoring completes
        with confirmed delivery status and latency strictly within the mandated 60,000ms SLA.
        """
        payload = {
            "incident_id": "inc-critical-trip-501",
            "channel": "PAGERDUTY",
            "message": "EMERGENCY: Valve lockup detected on Nitrogen feed regulator reg-line-4.",
        }
        response = client.post("/v1/dashboard/alerts", json=payload)
        assert response.status_code == 201
        data: Mapping[str, Any] = response.json()

        assert "dispatch_id" in data
        assert data["incident_id"] == "inc-critical-trip-501"
        assert data["channel"] == "PAGERDUTY"
        assert data["status"] in ["DELIVERED", "QUEUED"]
        assert "dispatched_at" in data
        # Non-functional requirement: sub-60s notification latency budget (< 60000ms)
        assert "latency_ms" in data
        assert data["latency_ms"] <= 60000, f"Alert latency {data['latency_ms']}ms exceeds 60s SLA"

    def test_us4_ac4_3_alert_routing_to_cloud_monitoring_channel(
        self, client: TestClient
    ) -> None:
        """[US-4][AC-4.3] Alert notification routing across alternative channels (Cloud Monitoring).

        Verifies multi-channel routing reliability for site safety officer escalation.
        """
        payload = {
            "incident_id": "inc-critical-trip-502",
            "channel": "CLOUD_MONITORING",
            "message": "CRITICAL: Sensor variance freeze detected on Oxygen regulator.",
        }
        response = client.post("/v1/dashboard/alerts", json=payload)
        assert response.status_code == 201
        data: Mapping[str, Any] = response.json()
        assert data["channel"] == "CLOUD_MONITORING"
        assert data["latency_ms"] <= 60000
