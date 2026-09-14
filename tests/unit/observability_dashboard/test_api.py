"""Unit tests for FastAPI entrypoints in api.py."""

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
    get_dashboard_service,
    reset_dependencies,
    set_dashboard_service,
)


@pytest.fixture(autouse=True)
def clean_dependencies() -> None:
    """Ensure dependencies are reset before and after each test."""
    reset_dependencies()
    yield
    reset_dependencies()


def _seed_sample_data(repo: InMemoryTelemetryRepository) -> None:
    now = datetime.now(UTC)
    r1 = RegulatorHealthRecord(
        regulator_id="reg-101",
        zone_id="zone-a",
        gate_status=GateStatus.NORMAL_REGULATION,
        current_flow_sccm=500.0,
        current_pressure_psi=45.0,
        current_temperature_c=25.0,
        variance_status=VarianceStatus.NORMAL,
        last_heartbeat=now,
    )
    r2 = RegulatorHealthRecord(
        regulator_id="reg-102",
        zone_id="zone-b",
        gate_status=GateStatus.FAIL_SAFE_HOLD,
        current_flow_sccm=0.0,
        current_pressure_psi=75.0,
        current_temperature_c=30.0,
        variance_status=VarianceStatus.FROZEN_SUSPECTED,
        last_heartbeat=now,
    )
    repo.save_regulator_health(r1)
    repo.save_regulator_health(r2)

    inc = IncidentRecord(
        incident_id="inc-999",
        regulator_id="reg-102",
        severity=SeverityLevel.CRITICAL,
        trip_reason="Pressure-flow divergence detected",
        root_cause_summary="",
        triggered_at=now,
        status=IncidentStatus.OPEN,
        pre_trip_telemetry_ref="gs://telemetry/inc-999.json",
    )
    repo.save_incident(inc)


def test_get_dashboard_health_success() -> None:
    """[US-4][AC-4.1] Test GET /v1/dashboard/health returns 200 and schema."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter()
    _seed_sample_data(repo)
    set_dashboard_service(repo, dispatcher)

    client = TestClient(app)
    response = client.get("/v1/dashboard/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "CRITICAL"  # Because reg-102 is FAIL_SAFE_HOLD
    assert data["active_regulators_count"] == 2
    assert data["healthy_count"] == 1
    assert data["tripped_count"] == 1
    assert len(data["gates"]) == 2


def test_get_dashboard_health_with_filters() -> None:
    """[US-4][AC-4.1] Test GET /v1/dashboard/health with zone and regulator filters."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter()
    _seed_sample_data(repo)
    set_dashboard_service(repo, dispatcher)

    client = TestClient(app)
    # Zone filter
    res = client.get("/v1/dashboard/health?zone_id=zone-a")
    assert res.status_code == 200
    assert res.json()["active_regulators_count"] == 1
    assert res.json()["gates"][0]["regulator_id"] == "reg-101"

    # Regulator filter
    res2 = client.get("/v1/dashboard/health?regulator_id=reg-102")
    assert res2.status_code == 200
    assert res2.json()["active_regulators_count"] == 1
    assert res2.json()["gates"][0]["regulator_id"] == "reg-102"


def test_get_dashboard_health_not_found() -> None:
    """[US-4][AC-4.1] Test GET /v1/dashboard/health with non-existent regulator returns 404."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter()
    _seed_sample_data(repo)
    set_dashboard_service(repo, dispatcher)

    client = TestClient(app)
    res = client.get("/v1/dashboard/health?regulator_id=reg-unknown")
    assert res.status_code == 404
    data = res.json()
    assert data["code"] == "RESOURCE_NOT_FOUND"


def test_get_dashboard_health_storage_failure() -> None:
    """[US-4][AC-4.1] Test GET /v1/dashboard/health datastore failure returns 500."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter()
    _seed_sample_data(repo)
    repo.set_fail_mode(True)
    set_dashboard_service(repo, dispatcher)

    client = TestClient(app)
    res = client.get("/v1/dashboard/health")
    assert res.status_code == 500
    assert res.json()["code"] == "STORAGE_UNAVAILABLE"


def test_get_incidents_success() -> None:
    """[US-4][AC-4.2] Test GET /v1/dashboard/incidents returns 200 and schema."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter()
    _seed_sample_data(repo)
    set_dashboard_service(repo, dispatcher)

    client = TestClient(app)
    res = client.get("/v1/dashboard/incidents?severity=CRITICAL&limit=10")
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] == 1
    assert len(data["incidents"]) == 1
    assert data["incidents"][0]["incident_id"] == "inc-999"
    assert "divergence" in data["incidents"][0]["root_cause_summary"].lower()


def test_get_incidents_bad_request() -> None:
    """[US-4][AC-4.2] Test GET /v1/dashboard/incidents invalid limit or severity returns 400."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter()
    _seed_sample_data(repo)
    set_dashboard_service(repo, dispatcher)

    client = TestClient(app)
    # limit > 200
    res = client.get("/v1/dashboard/incidents?limit=500")
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_FILTER"

    # invalid severity
    res2 = client.get("/v1/dashboard/incidents?severity=FATAL")
    assert res2.status_code == 400
    assert res2.json()["code"] == "INVALID_FILTER"


def test_get_incidents_not_found() -> None:
    """[US-4][AC-4.2] Test GET /v1/dashboard/incidents unknown regulator returns 404."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter()
    _seed_sample_data(repo)
    set_dashboard_service(repo, dispatcher)

    client = TestClient(app)
    res = client.get("/v1/dashboard/incidents?regulator_id=reg-unknown")
    assert res.status_code == 404
    assert res.json()["code"] == "RESOURCE_NOT_FOUND"


def test_get_incidents_storage_failure() -> None:
    """[US-4][AC-4.2] Test GET /v1/dashboard/incidents storage failure returns 500."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter()
    _seed_sample_data(repo)
    repo.set_fail_mode(True)
    set_dashboard_service(repo, dispatcher)

    client = TestClient(app)
    res = client.get("/v1/dashboard/incidents")
    assert res.status_code == 500
    assert res.json()["code"] == "STORAGE_UNAVAILABLE"


def test_post_dispatch_alert_success() -> None:
    """[US-4][AC-4.3] Test POST /v1/dashboard/alerts returns 201 Created and receipt schema."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter(simulated_latency_ms=180)
    _seed_sample_data(repo)
    set_dashboard_service(repo, dispatcher)

    client = TestClient(app)
    payload = {
        "incident_id": "inc-999",
        "channel": "PAGERDUTY",
        "message": "Immediate investigation required.",
    }
    res = client.post("/v1/dashboard/alerts", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["incident_id"] == "inc-999"
    assert data["channel"] == "PAGERDUTY"
    assert data["status"] == "DELIVERED"
    assert data["latency_ms"] == 180


def test_post_dispatch_alert_bad_request() -> None:
    """[US-4][AC-4.3] Test POST /v1/dashboard/alerts invalid payload returns 400."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter()
    _seed_sample_data(repo)
    set_dashboard_service(repo, dispatcher)

    client = TestClient(app)
    # Empty message
    res = client.post(
        "/v1/dashboard/alerts",
        json={"incident_id": "inc-999", "channel": "PAGERDUTY", "message": "   "},
    )
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_PAYLOAD"

    # Invalid channel
    res2 = client.post(
        "/v1/dashboard/alerts",
        json={"incident_id": "inc-999", "channel": "DISCORD", "message": "test"},
    )
    assert res2.status_code == 400
    assert res2.json()["code"] == "INVALID_PAYLOAD"


def test_post_dispatch_alert_not_found() -> None:
    """[US-4][AC-4.3] Test POST /v1/dashboard/alerts nonexistent incident returns 404."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter()
    _seed_sample_data(repo)
    set_dashboard_service(repo, dispatcher)

    client = TestClient(app)
    res = client.post(
        "/v1/dashboard/alerts",
        json={
            "incident_id": "inc-nonexistent",
            "channel": "PAGERDUTY",
            "message": "test",
        },
    )
    assert res.status_code == 404
    assert res.json()["code"] == "INCIDENT_NOT_FOUND"


def test_post_dispatch_alert_channel_outage() -> None:
    """[US-4][AC-4.3] Test POST /v1/dashboard/alerts downstream outage returns 500."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter()
    dispatcher.set_channel_outage(AlertChannel.PAGERDUTY, outage=True)
    _seed_sample_data(repo)
    set_dashboard_service(repo, dispatcher)

    client = TestClient(app)
    res = client.post(
        "/v1/dashboard/alerts",
        json={"incident_id": "inc-999", "channel": "PAGERDUTY", "message": "test"},
    )
    assert res.status_code == 500
    assert res.json()["code"] == "ALERT_DISPATCH_FAILED"


def test_get_dashboard_service_default_singleton() -> None:
    """Test get_dashboard_service lazily creates and returns singleton."""
    reset_dependencies()
    svc = get_dashboard_service()
    assert svc is not None
    # Second call returns same instance
    assert get_dashboard_service() is svc


def test_validation_error_handler() -> None:
    """Test RequestValidationError triggers 400 INVALID_PAYLOAD response."""
    app = create_app()
    client = TestClient(app)
    # Sending malformed json (e.g. integer instead of string for incident_id)
    res = client.post("/v1/dashboard/alerts", json={"incident_id": 123})
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_PAYLOAD"


def test_unexpected_internal_exceptions() -> None:
    """Test unexpected internal exceptions return 500 INTERNAL_ERROR."""
    app = create_app()
    repo = InMemoryTelemetryRepository()
    dispatcher = AlertNotifierAdapter()
    set_dashboard_service(repo, dispatcher)
    client = TestClient(app)

    # Monkeypatch resolve_health to raise RuntimeError
    svc = get_dashboard_service()
    orig_health = svc.resolve_health
    svc.resolve_health = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("Health crash")
    )  # type: ignore[assignment]
    res1 = client.get("/v1/dashboard/health")
    assert res1.status_code == 500
    assert res1.json()["code"] == "INTERNAL_ERROR"

    # Monkeypatch resolve_incidents to raise RuntimeError
    svc.resolve_health = orig_health  # type: ignore[assignment]
    orig_inc = svc.resolve_incidents
    svc.resolve_incidents = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("Incident crash")
    )  # type: ignore[assignment]
    res2 = client.get("/v1/dashboard/incidents")
    assert res2.status_code == 500
    assert res2.json()["code"] == "INTERNAL_ERROR"

    # Monkeypatch dispatch_alert to raise RuntimeError and InvalidPayloadError
    svc.resolve_incidents = orig_inc  # type: ignore[assignment]
    orig_dispatch = svc.dispatch_alert
    from src.modules.observability_dashboard.domain.exceptions import (
        InvalidPayloadError,
    )

    svc.dispatch_alert = lambda *args, **kwargs: (_ for _ in ()).throw(
        InvalidPayloadError("Payload invalid in svc")
    )  # type: ignore[assignment]
    res3 = client.post(
        "/v1/dashboard/alerts",
        json={"incident_id": "i", "channel": "PAGERDUTY", "message": "m"},
    )
    assert res3.status_code == 400
    assert res3.json()["code"] == "INVALID_PAYLOAD"

    svc.dispatch_alert = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("Dispatch crash")
    )  # type: ignore[assignment]
    res4 = client.post(
        "/v1/dashboard/alerts",
        json={"incident_id": "i", "channel": "PAGERDUTY", "message": "m"},
    )
    assert res4.status_code == 500
    assert res4.json()["code"] == "INTERNAL_ERROR"
    svc.dispatch_alert = orig_dispatch  # type: ignore[assignment]


def test_empty_filter_validation() -> None:
    """Test empty string query filters return 400 INVALID_FILTER."""
    app = create_app()
    client = TestClient(app)

    res_health_zone = client.get("/v1/dashboard/health?zone_id=")
    assert res_health_zone.status_code == 400
    assert res_health_zone.json()["code"] == "INVALID_FILTER"

    res_health_reg = client.get("/v1/dashboard/health?regulator_id=")
    assert res_health_reg.status_code == 400
    assert res_health_reg.json()["code"] == "INVALID_FILTER"

    res_inc_reg = client.get("/v1/dashboard/incidents?regulator_id=")
    assert res_inc_reg.status_code == 400
    assert res_inc_reg.json()["code"] == "INVALID_FILTER"
