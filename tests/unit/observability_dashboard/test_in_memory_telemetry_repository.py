"""Unit tests for InMemoryTelemetryRepository adapter."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.modules.observability_dashboard.adapters.in_memory_telemetry_repository import (
    InMemoryTelemetryRepository,
)
from src.modules.observability_dashboard.domain.exceptions import StorageUnavailableError
from src.modules.observability_dashboard.domain.models import (
    GateStatus,
    IncidentRecord,
    IncidentStatus,
    RegulatorHealthRecord,
    SeverityLevel,
    VarianceStatus,
)


def _sample_reg(reg_id: str, zone_id: str) -> RegulatorHealthRecord:
    return RegulatorHealthRecord(
        regulator_id=reg_id,
        zone_id=zone_id,
        gate_status=GateStatus.NORMAL_REGULATION,
        current_flow_sccm=100.0,
        current_pressure_psi=20.0,
        current_temperature_c=15.0,
        variance_status=VarianceStatus.NORMAL,
        last_heartbeat=datetime.now(UTC),
    )


def test_in_memory_repository_crud_and_queries() -> None:
    """[US-4][AC-4.1][AC-4.2] Test in-memory repository storage, query filters, and simulated failure."""
    repo = InMemoryTelemetryRepository()

    # Empty queries
    assert repo.get_regulator_health("reg-1") is None
    assert repo.check_regulator_exists("reg-1") is False
    assert repo.check_zone_exists("zone-a") is False
    assert repo.list_regulator_health() == []
    assert repo.list_incidents() == []
    assert repo.get_incident_by_id("inc-1") is None

    # Add regulators
    r1 = _sample_reg("reg-1", "zone-a")
    r2 = _sample_reg("reg-2", "zone-b")
    repo.save_regulator_health(r1)
    repo.save_regulator_health(r2)

    assert repo.check_regulator_exists("reg-1") is True
    assert repo.check_zone_exists("zone-a") is True
    assert repo.get_regulator_health("reg-1") == r1

    # List regulators by zone and id
    all_regs = repo.list_regulator_health()
    assert len(all_regs) == 2
    assert len(repo.list_regulator_health(zone_id="zone-a")) == 1
    assert len(repo.list_regulator_health(regulator_id="reg-2")) == 1
    assert len(repo.list_regulator_health(zone_id="zone-a", regulator_id="reg-1")) == 1
    assert len(repo.list_regulator_health(zone_id="zone-b", regulator_id="reg-1")) == 0

    # Add incidents
    now = datetime.now(UTC)
    inc1 = IncidentRecord(
        incident_id="inc-1",
        regulator_id="reg-1",
        severity=SeverityLevel.WARNING,
        trip_reason="Minor drift",
        root_cause_summary="Sensor drift",
        triggered_at=now,
        status=IncidentStatus.OPEN,
    )
    inc2 = IncidentRecord(
        incident_id="inc-2",
        regulator_id="reg-2",
        severity=SeverityLevel.CRITICAL,
        trip_reason="Pressure spike",
        root_cause_summary="Spike",
        triggered_at=now,
        status=IncidentStatus.ACKNOWLEDGED,
    )
    repo.save_incident(inc1)
    repo.save_incident(inc2)

    assert repo.get_incident_by_id("inc-1") == inc1
    assert len(repo.list_incidents()) == 2
    assert len(repo.list_incidents(severity=SeverityLevel.CRITICAL)) == 1
    assert len(repo.list_incidents(regulator_id="reg-1")) == 1
    assert len(repo.list_incidents(limit=1)) == 1

    # Simulate datastore failure
    repo.set_fail_mode(True)
    with pytest.raises(StorageUnavailableError):
        repo.get_regulator_health("reg-1")
    with pytest.raises(StorageUnavailableError):
        repo.list_regulator_health()
    with pytest.raises(StorageUnavailableError):
        repo.get_incident_by_id("inc-1")
    with pytest.raises(StorageUnavailableError):
        repo.list_incidents()
    with pytest.raises(StorageUnavailableError):
        repo.check_zone_exists("zone-a")
    with pytest.raises(StorageUnavailableError):
        repo.check_regulator_exists("reg-1")
    with pytest.raises(StorageUnavailableError):
        repo.save_regulator_health(r1)
    with pytest.raises(StorageUnavailableError):
        repo.save_incident(inc1)


def test_in_memory_repository_initial_seeds() -> None:
    """[US-4][AC-4.1][AC-4.2] Test constructor initialization with initial lists."""
    r = _sample_reg("reg-init", "zone-init")
    inc = IncidentRecord(
        incident_id="inc-init",
        regulator_id="reg-init",
        severity=SeverityLevel.WARNING,
        trip_reason="Test reason",
        root_cause_summary="Summary",
        triggered_at=datetime.now(UTC),
        status=IncidentStatus.OPEN,
    )
    repo = InMemoryTelemetryRepository(
        initial_regulators=[r],
        initial_incidents=[inc],
    )
    assert repo.get_regulator_health("reg-init") == r
    assert repo.get_incident_by_id("inc-init") == inc

