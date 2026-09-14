"""Integration tests for observability_dashboard subsystem wiring domain, adapters, and entrypoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.modules.observability_dashboard.adapters.alert_notifier_adapter import (
    AlertNotifierAdapter,
)
from src.modules.observability_dashboard.adapters.in_memory_telemetry_repository import (
    InMemoryTelemetryRepository,
)
from src.modules.observability_dashboard.domain.models import (
    AlertChannel,
    GateStatus,
    IncidentRecord,
    IncidentStatus,
    RegulatorHealthRecord,
    SeverityLevel,
    VarianceStatus,
)
from src.modules.observability_dashboard.entrypoints.api import (
    create_app,
    reset_dependencies,
    set_dashboard_service,
)


@pytest.fixture(autouse=True)
def clean_dependencies() -> None:
    """Ensure clean dependency state before and after each integration test."""
    reset_dependencies()
    yield
    reset_dependencies()


def test_full_operational_lifecycle_integration() -> None:
    """[US-4][AC-4.1][AC-4.2][AC-4.3] Test end-to-end integration across repository, service, and API."""
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter(simulated_latency_ms=95)
    set_dashboard_service(repo, dispatcher)

    app = create_app()
    client = TestClient(app)

    # 1. Initially empty health
    res_health = client.get("/v1/dashboard/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "HEALTHY"
    assert res_health.json()["active_regulators_count"] == 0

    # 2. Ingest telemetry snapshot into repository
    now = datetime.now(UTC)
    r1 = RegulatorHealthRecord(
        regulator_id="reg-alpha-01",
        zone_id="zone-cracking",
        gate_status=GateStatus.NORMAL_REGULATION,
        current_flow_sccm=1250.0,
        current_pressure_psi=50.2,
        current_temperature_c=24.1,
        variance_status=VarianceStatus.NORMAL,
        last_heartbeat=now,
    )
    repo.save_regulator_health(r1)

    # Health check shows 1 healthy regulator
    res_health2 = client.get("/v1/dashboard/health")
    assert res_health2.status_code == 200
    assert res_health2.json()["active_regulators_count"] == 1
    assert res_health2.json()["healthy_count"] == 1
    assert res_health2.json()["status"] == "HEALTHY"

    # 3. Simulate trip and record incident
    r1_tripped = RegulatorHealthRecord(
        regulator_id="reg-alpha-01",
        zone_id="zone-cracking",
        gate_status=GateStatus.CLOSE_GATE_LOCKED,
        current_flow_sccm=0.0,
        current_pressure_psi=88.5,
        current_temperature_c=35.0,
        variance_status=VarianceStatus.ERRATIC,
        last_heartbeat=now,
    )
    repo.save_regulator_health(r1_tripped)

    inc = IncidentRecord(
        incident_id="inc-uuid-101",
        regulator_id="reg-alpha-01",
        severity=SeverityLevel.EMERGENCY,
        trip_reason="Overpressure and flow spike divergence",
        root_cause_summary="",  # Domain will enrich
        triggered_at=now,
        status=IncidentStatus.OPEN,
        pre_trip_telemetry_ref="gs://bucket/pre-trip-101.json",
    )
    repo.save_incident(inc)

    # Health check now shows CRITICAL status and 1 tripped
    res_health3 = client.get("/v1/dashboard/health")
    assert res_health3.status_code == 200
    assert res_health3.json()["status"] == "CRITICAL"
    assert res_health3.json()["tripped_count"] == 1

    # Query incidents: verify automated diagnosis enriched
    res_inc = client.get("/v1/dashboard/incidents?severity=EMERGENCY")
    assert res_inc.status_code == 200
    inc_data = res_inc.json()
    assert inc_data["total_count"] == 1
    assert "divergence" in inc_data["incidents"][0]["root_cause_summary"].lower()

    # 4. Dispatch emergency alert to PagerDuty
    alert_payload = {
        "incident_id": "inc-uuid-101",
        "channel": "PAGERDUTY",
        "message": "Immediate site inspection needed in zone-cracking.",
    }
    res_alert = client.post("/v1/dashboard/alerts", json=alert_payload)
    assert res_alert.status_code == 201
    receipt_data = res_alert.json()
    assert receipt_data["status"] == "DELIVERED"
    assert receipt_data["channel"] == "PAGERDUTY"
    assert receipt_data["latency_ms"] == 95
    assert len(dispatcher.dispatched) == 1
