"""Canonical Contract Verification Test Suite for observability_dashboard.

Validates that subsystem HTTP entrypoints strictly adhere to the frozen openapi.yaml
interface contract, including HTTP status codes, response schemas, error structures,
and routing version conventions.

Treats the subsystem as a black box: imports ONLY the public entrypoint app,
never internal `domain/` or `adapters/` classes.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

FROZEN_CONTRACT = Path("src/modules/observability_dashboard/openapi.yaml")


class TestContractConformance:
    """Black-box contract compliance test suite for observability_dashboard."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Instantiate test client for the subsystem public entrypoint."""
        from src.modules.observability_dashboard.entrypoints.api import app

        return TestClient(app)

    @pytest.fixture
    def frozen_contract(self) -> Mapping[str, Any]:
        """Load the frozen openapi.yaml the running app must satisfy."""
        return yaml.safe_load(FROZEN_CONTRACT.read_text(encoding="utf-8"))

    def test_live_app_conforms_to_frozen_contract(
        self, client: TestClient, frozen_contract: Mapping[str, Any]
    ) -> None:
        """Verify every path/method/status in the frozen contract is served by the live app."""
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
        """Verify that all exposed paths are versioned with /v1/ prefix."""
        for path in frozen_contract.get("paths", {}):
            assert path.startswith("/v1/"), f"Path '{path}' violates /v1/ versioning contract."

    # --- GET /v1/dashboard/health Contract Tests (200, 400, 404, 500) ---

    def test_get_dashboard_health_returns_200_and_valid_schema(self, client: TestClient) -> None:
        """Verify GET /v1/dashboard/health returns 200 OK and conforms to DashboardHealthResponse."""
        response = client.get("/v1/dashboard/health")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        data: Mapping[str, Any] = response.json()
        assert "status" in data
        assert data["status"] in ["HEALTHY", "DEGRADED", "CRITICAL"]
        assert "timestamp" in data
        assert "active_regulators_count" in data
        assert "healthy_count" in data
        assert "degraded_count" in data
        assert "tripped_count" in data
        assert "gates" in data
        assert isinstance(data["gates"], list)
        if data["gates"]:
            gate = data["gates"][0]
            assert "regulator_id" in gate
            assert "zone_id" in gate
            assert "gate_status" in gate
            assert "current_flow_sccm" in gate
            assert "current_pressure_psi" in gate
            assert "current_temperature_c" in gate
            assert "variance_status" in gate
            assert "last_heartbeat" in gate

    def test_get_dashboard_health_invalid_filter_returns_400(self, client: TestClient) -> None:
        """Verify GET /v1/dashboard/health returns 400 Bad Request on invalid query parameters."""
        response = client.get("/v1/dashboard/health", params={"zone_id": ""})
        assert response.status_code == 400
        error_body: Mapping[str, Any] = response.json()
        assert "code" in error_body
        assert "message" in error_body

    def test_get_dashboard_health_unknown_regulator_returns_404(self, client: TestClient) -> None:
        """Verify GET /v1/dashboard/health returns 404 Not Found when regulator is not found."""
        response = client.get("/v1/dashboard/health", params={"regulator_id": "nonexistent-reg-999"})
        assert response.status_code == 404
        error_body: Mapping[str, Any] = response.json()
        assert "code" in error_body
        assert "message" in error_body

    def test_get_dashboard_health_datastore_failure_returns_500(self, client: TestClient) -> None:
        """Verify GET /v1/dashboard/health returns 500 Internal Server Error without leaking internals."""
        response = client.get("/v1/dashboard/health", headers={"X-Test-Fault-Injection": "datastore-error"})
        assert response.status_code == 500
        error_body: Mapping[str, Any] = response.json()
        assert "code" in error_body
        assert "message" in error_body
        assert "Traceback" not in response.text

    # --- GET /v1/dashboard/incidents Contract Tests (200, 400, 404, 500) ---

    def test_get_incidents_returns_200_and_valid_schema(self, client: TestClient) -> None:
        """Verify GET /v1/dashboard/incidents returns 200 OK and conforms to IncidentListResponse."""
        response = client.get("/v1/dashboard/incidents")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        data: Mapping[str, Any] = response.json()
        assert "incidents" in data
        assert "total_count" in data
        assert "timestamp" in data
        assert isinstance(data["incidents"], list)
        if data["incidents"]:
            incident = data["incidents"][0]
            assert "incident_id" in incident
            assert "regulator_id" in incident
            assert "severity" in incident
            assert incident["severity"] in ["WARNING", "CRITICAL", "EMERGENCY"]
            assert "trip_reason" in incident
            assert "root_cause_summary" in incident
            assert "triggered_at" in incident
            assert "status" in incident
            assert incident["status"] in ["OPEN", "ACKNOWLEDGED", "RESOLVED"]

    def test_get_incidents_invalid_severity_returns_400(self, client: TestClient) -> None:
        """Verify GET /v1/dashboard/incidents returns 400 Bad Request on invalid severity filter."""
        response = client.get("/v1/dashboard/incidents", params={"severity": "INVALID_SEVERITY"})
        assert response.status_code == 400
        error_body: Mapping[str, Any] = response.json()
        assert "code" in error_body
        assert "message" in error_body

    def test_get_incidents_unknown_regulator_returns_404(self, client: TestClient) -> None:
        """Verify GET /v1/dashboard/incidents returns 404 Not Found when filtering by nonexistent regulator."""
        response = client.get("/v1/dashboard/incidents", params={"regulator_id": "nonexistent-reg-999"})
        assert response.status_code == 404
        error_body: Mapping[str, Any] = response.json()
        assert "code" in error_body
        assert "message" in error_body

    def test_get_incidents_datastore_failure_returns_500(self, client: TestClient) -> None:
        """Verify GET /v1/dashboard/incidents returns 500 Internal Server Error without leaking internals."""
        response = client.get("/v1/dashboard/incidents", headers={"X-Test-Fault-Injection": "datastore-error"})
        assert response.status_code == 500
        error_body: Mapping[str, Any] = response.json()
        assert "code" in error_body
        assert "message" in error_body
        assert "Traceback" not in response.text

    # --- POST /v1/dashboard/alerts Contract Tests (201, 400, 404, 500) ---

    def test_post_dispatch_alert_returns_201_and_valid_schema(self, client: TestClient) -> None:
        """Verify POST /v1/dashboard/alerts returns 201 Created and conforms to AlertDispatchResponse."""
        payload = {
            "incident_id": "inc-uuid-1001",
            "channel": "PAGERDUTY",
            "message": "Critical pressure-flow divergence trip on line 4.",
        }
        response = client.post("/v1/dashboard/alerts", json=payload)
        assert response.status_code == 201
        assert response.headers["content-type"].startswith("application/json")
        data: Mapping[str, Any] = response.json()
        assert "dispatch_id" in data
        assert data["incident_id"] == "inc-uuid-1001"
        assert data["channel"] == "PAGERDUTY"
        assert data["status"] in ["DELIVERED", "QUEUED", "FAILED"]
        assert "dispatched_at" in data
        assert "latency_ms" in data
        assert isinstance(data["latency_ms"], int)

    def test_post_dispatch_alert_malformed_payload_returns_400(self, client: TestClient) -> None:
        """Verify POST /v1/dashboard/alerts returns 400 Bad Request on missing required fields."""
        invalid_payload = {"incident_id": "inc-uuid-1001"}
        response = client.post("/v1/dashboard/alerts", json=invalid_payload)
        assert response.status_code == 400
        error_body: Mapping[str, Any] = response.json()
        assert "code" in error_body
        assert "message" in error_body

    def test_post_dispatch_alert_nonexistent_incident_returns_404(self, client: TestClient) -> None:
        """Verify POST /v1/dashboard/alerts returns 404 Not Found when incident does not exist."""
        payload = {
            "incident_id": "nonexistent-incident-uuid",
            "channel": "CLOUD_MONITORING",
            "message": "Alert for missing incident.",
        }
        response = client.post("/v1/dashboard/alerts", json=payload)
        assert response.status_code == 404
        error_body: Mapping[str, Any] = response.json()
        assert "code" in error_body
        assert "message" in error_body

    def test_post_dispatch_alert_channel_outage_returns_500(self, client: TestClient) -> None:
        """Verify POST /v1/dashboard/alerts returns 500 Internal Server Error without leaking internals."""
        payload = {
            "incident_id": "trigger_channel_error",
            "channel": "SMS_SAFETY_OFFICER",
            "message": "Test simulated notification provider failure.",
        }
        response = client.post("/v1/dashboard/alerts", json=payload)
        assert response.status_code == 500
        error_body: Mapping[str, Any] = response.json()
        assert "code" in error_body
        assert "message" in error_body
        assert "Traceback" not in response.text
