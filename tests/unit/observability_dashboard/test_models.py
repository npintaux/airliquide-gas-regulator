"""Unit tests for domain models."""

from __future__ import annotations

from datetime import UTC, datetime

from src.modules.observability_dashboard.domain.models import (
    AlertChannel,
    AlertDispatchCommand,
    AlertDispatchReceipt,
    AlertStatus,
    DashboardHealthSnapshot,
    FleetStatus,
    GateStatus,
    IncidentRecord,
    IncidentStatus,
    RegulatorHealthRecord,
    SeverityLevel,
    VarianceStatus,
)


def test_models_creation_and_attributes() -> None:
    """[US-4][AC-4.1][AC-4.2][AC-4.3] Test creation of immutable domain models."""
    now = datetime.now(UTC)

    # Enums
    assert GateStatus.NORMAL_REGULATION == "NORMAL_REGULATION"
    assert FleetStatus.HEALTHY == "HEALTHY"
    assert SeverityLevel.CRITICAL == "CRITICAL"
    assert AlertChannel.PAGERDUTY == "PAGERDUTY"
    assert VarianceStatus.NORMAL == "NORMAL"
    assert IncidentStatus.OPEN == "OPEN"
    assert AlertStatus.DELIVERED == "DELIVERED"

    # RegulatorHealthRecord
    reg = RegulatorHealthRecord(
        regulator_id="reg-1",
        zone_id="zone-a",
        gate_status=GateStatus.NORMAL_REGULATION,
        current_flow_sccm=500.0,
        current_pressure_psi=45.0,
        current_temperature_c=22.5,
        variance_status=VarianceStatus.NORMAL,
        last_heartbeat=now,
    )
    assert reg.regulator_id == "reg-1"
    assert reg.zone_id == "zone-a"
    assert reg.gate_status == GateStatus.NORMAL_REGULATION
    assert reg.current_flow_sccm == 500.0

    # DashboardHealthSnapshot
    snapshot = DashboardHealthSnapshot(
        status=FleetStatus.HEALTHY,
        timestamp=now,
        active_regulators_count=1,
        healthy_count=1,
        degraded_count=0,
        tripped_count=0,
        gates=(reg,),
    )
    assert snapshot.status == FleetStatus.HEALTHY
    assert snapshot.active_regulators_count == 1
    assert len(snapshot.gates) == 1

    # IncidentRecord
    inc = IncidentRecord(
        incident_id="inc-1",
        regulator_id="reg-1",
        severity=SeverityLevel.CRITICAL,
        trip_reason="Overpressure detected",
        root_cause_summary="Pressure-flow divergence exceeds threshold",
        triggered_at=now,
        status=IncidentStatus.OPEN,
        pre_trip_telemetry_ref="gs://telemetry/inc-1.json",
    )
    assert inc.incident_id == "inc-1"
    assert inc.pre_trip_telemetry_ref == "gs://telemetry/inc-1.json"

    # AlertDispatchCommand
    cmd = AlertDispatchCommand(
        incident_id="inc-1",
        channel=AlertChannel.PAGERDUTY,
        message="Critical pressure alert",
    )
    assert cmd.incident_id == "inc-1"
    assert cmd.channel == AlertChannel.PAGERDUTY

    # AlertDispatchReceipt
    receipt = AlertDispatchReceipt(
        dispatch_id="disp-1",
        incident_id="inc-1",
        channel=AlertChannel.PAGERDUTY,
        status=AlertStatus.DELIVERED,
        dispatched_at=now,
        latency_ms=120,
    )
    assert receipt.dispatch_id == "disp-1"
    assert receipt.latency_ms == 120
