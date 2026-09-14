"""Unit tests for DashboardService."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.modules.observability_dashboard.domain.alert_dispatcher import AlertDispatchPort
from src.modules.observability_dashboard.domain.exceptions import (
    AlertDispatchError,
    DispatchTimeoutError,
    IncidentNotFoundError,
    InvalidFilterError,
    InvalidPayloadError,
    ResourceNotFoundError,
)
from src.modules.observability_dashboard.domain.models import (
    AlertChannel,
    AlertDispatchCommand,
    AlertDispatchReceipt,
    AlertStatus,
    FleetStatus,
    GateStatus,
    IncidentRecord,
    IncidentStatus,
    RegulatorHealthRecord,
    SeverityLevel,
    VarianceStatus,
)
from src.modules.observability_dashboard.domain.repository import DashboardRepository
from src.modules.observability_dashboard.domain.service import DashboardService
from src.modules.observability_dashboard.domain.summarizer import RootCauseSummarizer


class MockRepository(DashboardRepository):
    """Test fake repository implementation."""

    def __init__(self) -> None:
        self.regulators: dict[str, RegulatorHealthRecord] = {}
        self.incidents: dict[str, IncidentRecord] = {}
        self.valid_zones: set[str] = {"zone-a", "zone-b"}

    def get_regulator_health(self, regulator_id: str) -> RegulatorHealthRecord | None:
        return self.regulators.get(regulator_id)

    def list_regulator_health(
        self, zone_id: str | None = None, regulator_id: str | None = None
    ) -> list[RegulatorHealthRecord]:
        results = list(self.regulators.values())
        if zone_id:
            results = [r for r in results if r.zone_id == zone_id]
        if regulator_id:
            results = [r for r in results if r.regulator_id == regulator_id]
        return results

    def list_incidents(
        self,
        limit: int = 50,
        severity: SeverityLevel | None = None,
        regulator_id: str | None = None,
    ) -> list[IncidentRecord]:
        results = list(self.incidents.values())
        if severity:
            results = [i for i in results if i.severity == severity]
        if regulator_id:
            results = [i for i in results if i.regulator_id == regulator_id]
        results.sort(key=lambda i: i.triggered_at, reverse=True)
        return results[:limit]

    def get_incident_by_id(self, incident_id: str) -> IncidentRecord | None:
        return self.incidents.get(incident_id)

    def check_zone_exists(self, zone_id: str) -> bool:
        return zone_id in self.valid_zones

    def check_regulator_exists(self, regulator_id: str) -> bool:
        return regulator_id in self.regulators


class MockAlertDispatcher(AlertDispatchPort):
    """Test fake alert dispatcher."""

    def __init__(self, latency_ms: int = 150, fail: bool = False) -> None:
        self.latency_ms = latency_ms
        self.fail = fail
        self.dispatched_commands: list[AlertDispatchCommand] = []

    def dispatch_alert(self, command: AlertDispatchCommand) -> AlertDispatchReceipt:
        if self.fail:
            raise AlertDispatchError("Downstream provider unreachable")
        self.dispatched_commands.append(command)
        return AlertDispatchReceipt(
            dispatch_id="receipt-test-1",
            incident_id=command.incident_id,
            channel=command.channel,
            status=AlertStatus.DELIVERED,
            dispatched_at=datetime.now(UTC),
            latency_ms=self.latency_ms,
        )


def _sample_regulator(
    reg_id: str = "reg-1",
    zone_id: str = "zone-a",
    gate_status: GateStatus = GateStatus.NORMAL_REGULATION,
) -> RegulatorHealthRecord:
    return RegulatorHealthRecord(
        regulator_id=reg_id,
        zone_id=zone_id,
        gate_status=gate_status,
        current_flow_sccm=500.0,
        current_pressure_psi=45.0,
        current_temperature_c=25.0,
        variance_status=VarianceStatus.NORMAL,
        last_heartbeat=datetime.now(UTC),
    )


def test_resolve_health_empty() -> None:
    """[US-4][AC-4.1] Empty fleet produces HEALTHY snapshot with 0 counts."""
    repo = MockRepository()
    dispatcher = MockAlertDispatcher()
    service = DashboardService(repo, dispatcher)

    snapshot = service.resolve_health()
    assert snapshot.status == FleetStatus.HEALTHY
    assert snapshot.active_regulators_count == 0
    assert snapshot.healthy_count == 0
    assert snapshot.degraded_count == 0
    assert snapshot.tripped_count == 0
    assert snapshot.gates == ()


def test_resolve_health_categorization() -> None:
    """[US-4][AC-4.1] Aggregates counts and derives fleet status correctly."""
    repo = MockRepository()
    dispatcher = MockAlertDispatcher()
    service = DashboardService(repo, dispatcher)

    # 1 Healthy
    r1 = _sample_regulator("reg-1", "zone-a", GateStatus.NORMAL_REGULATION)
    repo.regulators["reg-1"] = r1
    snap1 = service.resolve_health()
    assert snap1.status == FleetStatus.HEALTHY
    assert snap1.healthy_count == 1

    # Add Degraded
    r2 = _sample_regulator("reg-2", "zone-a", GateStatus.MINIMUM_SAFE_FLOW)
    r3 = _sample_regulator("reg-3", "zone-b", GateStatus.OFFLINE_FALLBACK)
    repo.regulators["reg-2"] = r2
    repo.regulators["reg-3"] = r3
    snap2 = service.resolve_health()
    assert snap2.status == FleetStatus.DEGRADED
    assert snap2.healthy_count == 1
    assert snap2.degraded_count == 2
    assert snap2.tripped_count == 0

    # Add Tripped (CRITICAL)
    r4 = _sample_regulator("reg-4", "zone-b", GateStatus.CLOSE_GATE_LOCKED)
    repo.regulators["reg-4"] = r4
    snap3 = service.resolve_health()
    assert snap3.status == FleetStatus.CRITICAL
    assert snap3.tripped_count == 1

    # Also FAIL_SAFE_HOLD is counted as tripped
    r5 = _sample_regulator("reg-5", "zone-a", GateStatus.FAIL_SAFE_HOLD)
    repo.regulators["reg-5"] = r5
    snap4 = service.resolve_health()
    assert snap4.tripped_count == 2


def test_resolve_health_filtering() -> None:
    """[US-4][AC-4.1] Filters health by zone_id and regulator_id."""
    repo = MockRepository()
    dispatcher = MockAlertDispatcher()
    service = DashboardService(repo, dispatcher)

    repo.regulators["reg-1"] = _sample_regulator("reg-1", "zone-a")
    repo.regulators["reg-2"] = _sample_regulator("reg-2", "zone-b")

    # Filter by valid zone
    snap_zone = service.resolve_health(zone_id="zone-a")
    assert snap_zone.active_regulators_count == 1
    assert snap_zone.gates[0].regulator_id == "reg-1"

    # Filter by valid regulator
    snap_reg = service.resolve_health(regulator_id="reg-2")
    assert snap_reg.active_regulators_count == 1
    assert snap_reg.gates[0].regulator_id == "reg-2"

    # Filter by unknown zone
    with pytest.raises(ResourceNotFoundError, match="Zone 'zone-unknown' not found"):
        service.resolve_health(zone_id="zone-unknown")

    # Filter by unknown regulator
    with pytest.raises(ResourceNotFoundError, match="Regulator 'reg-unknown' not found"):
        service.resolve_health(regulator_id="reg-unknown")


def test_resolve_incidents_validation_and_filtering() -> None:
    """[US-4][AC-4.2] Validates query bounds, filters, and enriches root cause summary."""
    repo = MockRepository()
    dispatcher = MockAlertDispatcher()
    service = DashboardService(repo, dispatcher)

    # Invalid limits
    with pytest.raises(InvalidFilterError, match="Limit must be between 1 and 200"):
        service.resolve_incidents(limit=0)
    with pytest.raises(InvalidFilterError, match="Limit must be between 1 and 200"):
        service.resolve_incidents(limit=201)

    # Unknown regulator
    with pytest.raises(ResourceNotFoundError, match="Regulator 'reg-999' not found"):
        service.resolve_incidents(regulator_id="reg-999")

    # Seed incidents
    repo.regulators["reg-1"] = _sample_regulator("reg-1")
    now = datetime.now(UTC)
    repo.incidents["inc-1"] = IncidentRecord(
        incident_id="inc-1",
        regulator_id="reg-1",
        severity=SeverityLevel.CRITICAL,
        trip_reason="Pressure-flow divergence detected",
        root_cause_summary="",  # Will be enriched
        triggered_at=now,
        status=IncidentStatus.OPEN,
    )
    repo.incidents["inc-2"] = IncidentRecord(
        incident_id="inc-2",
        regulator_id="reg-1",
        severity=SeverityLevel.WARNING,
        trip_reason="High temperature drift",
        root_cause_summary="Pre-existing summary",
        triggered_at=now,
        status=IncidentStatus.RESOLVED,
    )

    incidents, count = service.resolve_incidents(limit=10, severity=SeverityLevel.CRITICAL)
    assert count == 1
    assert len(incidents) == 1
    assert incidents[0].incident_id == "inc-1"
    assert "divergence" in incidents[0].root_cause_summary.lower()

    # Filter by regulator_id
    incidents_all, count_all = service.resolve_incidents(limit=10, regulator_id="reg-1")
    assert count_all == 2
    assert incidents_all[1].root_cause_summary == "Pre-existing summary"


def test_dispatch_alert_validation_and_execution() -> None:
    """[US-4][AC-4.3] Validates command payload, verifies incident existence, routes alert."""
    repo = MockRepository()
    dispatcher = MockAlertDispatcher(latency_ms=100)
    service = DashboardService(repo, dispatcher)

    # Empty payload fields
    with pytest.raises(InvalidPayloadError, match="incident_id cannot be empty"):
        service.dispatch_alert(
            AlertDispatchCommand(incident_id="", channel=AlertChannel.PAGERDUTY, message="Alert")
        )
    with pytest.raises(InvalidPayloadError, match="message cannot be empty"):
        service.dispatch_alert(
            AlertDispatchCommand(incident_id="inc-1", channel=AlertChannel.PAGERDUTY, message="")
        )

    # Nonexistent incident
    with pytest.raises(IncidentNotFoundError, match="Incident 'inc-1' not found"):
        service.dispatch_alert(
            AlertDispatchCommand(incident_id="inc-1", channel=AlertChannel.PAGERDUTY, message="Alert")
        )

    # Existing incident
    repo.incidents["inc-1"] = IncidentRecord(
        incident_id="inc-1",
        regulator_id="reg-1",
        severity=SeverityLevel.CRITICAL,
        trip_reason="Pressure divergence",
        root_cause_summary="Enriched",
        triggered_at=datetime.now(UTC),
        status=IncidentStatus.OPEN,
    )

    receipt = service.dispatch_alert(
        AlertDispatchCommand(
            incident_id="inc-1",
            channel=AlertChannel.PAGERDUTY,
            message="Alert message",
        )
    )
    assert receipt.dispatch_id == "receipt-test-1"
    assert receipt.incident_id == "inc-1"
    assert receipt.status == AlertStatus.DELIVERED
    assert receipt.latency_ms == 100


def test_dispatch_alert_timeout_and_error() -> None:
    """[US-4][AC-4.3] Enforces SLA budget and handles dispatcher errors."""
    repo = MockRepository()
    repo.incidents["inc-1"] = IncidentRecord(
        incident_id="inc-1",
        regulator_id="reg-1",
        severity=SeverityLevel.CRITICAL,
        trip_reason="Pressure divergence",
        root_cause_summary="Enriched",
        triggered_at=datetime.now(UTC),
        status=IncidentStatus.OPEN,
    )

    # Timeout > 60000ms
    timeout_dispatcher = MockAlertDispatcher(latency_ms=65000)
    service_timeout = DashboardService(repo, timeout_dispatcher)
    with pytest.raises(DispatchTimeoutError, match="Dispatch exceeded SLA budget"):
        service_timeout.dispatch_alert(
            AlertDispatchCommand(incident_id="inc-1", channel=AlertChannel.PAGERDUTY, message="msg")
        )

    # Downstream error
    err_dispatcher = MockAlertDispatcher(fail=True)
    service_err = DashboardService(repo, err_dispatcher)
    with pytest.raises(AlertDispatchError, match="Downstream provider unreachable"):
        service_err.dispatch_alert(
            AlertDispatchCommand(incident_id="inc-1", channel=AlertChannel.PAGERDUTY, message="msg")
        )
