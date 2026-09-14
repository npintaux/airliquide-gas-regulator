"""In-memory telemetry and incident repository adapter."""

from __future__ import annotations

from datetime import UTC, datetime

from ..domain.exceptions import StorageUnavailableError
from ..domain.models import (
    GateStatus,
    IncidentRecord,
    IncidentStatus,
    RegulatorHealthRecord,
    SeverityLevel,
    VarianceStatus,
)
from ..domain.repository import DashboardRepository


class InMemoryTelemetryRepository(DashboardRepository):
    """In-memory dictionary-backed repository implementing DashboardRepository."""

    def __init__(
        self,
        initial_regulators: list[RegulatorHealthRecord] | None = None,
        initial_incidents: list[IncidentRecord] | None = None,
    ) -> None:
        """Initialize in-memory storage.

        Args:
            initial_regulators: Optional pre-populated list of regulator health records.
            initial_incidents: Optional pre-populated list of incident records.
        """
        self._regulators: dict[str, RegulatorHealthRecord] = {}
        self._incidents: dict[str, IncidentRecord] = {}
        self._zones: set[str] = set()
        self._fail_mode: bool = False

        if initial_regulators:
            for reg in initial_regulators:
                self.save_regulator_health(reg)

        if initial_incidents:
            for inc in initial_incidents:
                self.save_incident(inc)

    def set_fail_mode(self, fail: bool) -> None:
        """Toggle simulated datastore outage mode.

        Args:
            fail: True to simulate storage outage, False for normal operation.
        """
        self._fail_mode = fail

    def _check_availability(self) -> None:
        """Check if storage is simulated as available.

        Raises:
            StorageUnavailableError: If fail mode is active.
        """
        if self._fail_mode:
            raise StorageUnavailableError("Datastore connection failed or timed out.")

    def save_regulator_health(self, record: RegulatorHealthRecord) -> None:
        """Persist or update regulator operational snapshot.

        Args:
            record: Regulator health snapshot to store.

        Raises:
            StorageUnavailableError: If storage is unavailable.
        """
        self._check_availability()
        self._regulators[record.regulator_id] = record
        self._zones.add(record.zone_id)

    def save_incident(self, incident: IncidentRecord) -> None:
        """Persist an incident record.

        Args:
            incident: Incident record to store.

        Raises:
            StorageUnavailableError: If storage is unavailable.
        """
        self._check_availability()
        self._incidents[incident.incident_id] = incident

    def get_regulator_health(self, regulator_id: str) -> RegulatorHealthRecord | None:
        """Fetch health record for a regulator by ID.

        Args:
            regulator_id: Regulator unique identifier.

        Returns:
            RegulatorHealthRecord if found, else None.

        Raises:
            StorageUnavailableError: If storage is unavailable.
        """
        self._check_availability()
        return self._regulators.get(regulator_id)

    def list_regulator_health(
        self,
        zone_id: str | None = None,
        regulator_id: str | None = None,
    ) -> list[RegulatorHealthRecord]:
        """Query regulator records filtered by zone or regulator.

        Args:
            zone_id: Optional zone filter.
            regulator_id: Optional regulator filter.

        Returns:
            List of matching records.

        Raises:
            StorageUnavailableError: If storage is unavailable.
        """
        self._check_availability()
        records = list(self._regulators.values())
        if zone_id:
            records = [r for r in records if r.zone_id == zone_id]
        if regulator_id:
            records = [r for r in records if r.regulator_id == regulator_id]
        return records

    def list_incidents(
        self,
        limit: int = 50,
        severity: SeverityLevel | None = None,
        regulator_id: str | None = None,
    ) -> list[IncidentRecord]:
        """Query incident records matching criteria.

        Args:
            limit: Maximum count to return.
            severity: Optional severity filter.
            regulator_id: Optional regulator filter.

        Returns:
            List of matching incidents sorted by triggered_at descending.

        Raises:
            StorageUnavailableError: If storage is unavailable.
        """
        self._check_availability()
        records = list(self._incidents.values())
        if severity:
            records = [i for i in records if i.severity == severity]
        if regulator_id:
            records = [i for i in records if i.regulator_id == regulator_id]
        records.sort(key=lambda i: i.triggered_at, reverse=True)
        return records[:limit]

    def get_incident_by_id(self, incident_id: str) -> IncidentRecord | None:
        """Fetch incident by unique incident ID.

        Args:
            incident_id: Incident UUID.

        Returns:
            IncidentRecord if found, else None.

        Raises:
            StorageUnavailableError: If storage is unavailable.
        """
        self._check_availability()
        return self._incidents.get(incident_id)

    def check_zone_exists(self, zone_id: str) -> bool:
        """Verify existence of a zone.

        Args:
            zone_id: Zone identifier.

        Returns:
            True if zone exists, False otherwise.

        Raises:
            StorageUnavailableError: If storage is unavailable.
        """
        self._check_availability()
        return zone_id in self._zones

    def check_regulator_exists(self, regulator_id: str) -> bool:
        """Verify existence of a regulator.

        Args:
            regulator_id: Regulator identifier.

        Returns:
            True if regulator exists, False otherwise.

        Raises:
            StorageUnavailableError: If storage is unavailable.
        """
        self._check_availability()
        return regulator_id in self._regulators

    def seed_defaults(self) -> None:
        """Seed default plant regulators and incident records for black-box operation."""
        now = datetime.now(UTC)
        defaults_regs = [
            RegulatorHealthRecord(
                regulator_id="reg-line-4",
                zone_id="zone-a",
                gate_status=GateStatus.NORMAL_REGULATION,
                current_flow_sccm=500.0,
                current_pressure_psi=45.0,
                current_temperature_c=25.0,
                variance_status=VarianceStatus.NORMAL,
                last_heartbeat=now,
            ),
            RegulatorHealthRecord(
                regulator_id="reg-line-2",
                zone_id="zone-a",
                gate_status=GateStatus.MINIMUM_SAFE_FLOW,
                current_flow_sccm=150.0,
                current_pressure_psi=48.0,
                current_temperature_c=24.0,
                variance_status=VarianceStatus.NORMAL,
                last_heartbeat=now,
            ),
            RegulatorHealthRecord(
                regulator_id="reg-line-9",
                zone_id="zone-b",
                gate_status=GateStatus.NORMAL_REGULATION,
                current_flow_sccm=480.0,
                current_pressure_psi=44.0,
                current_temperature_c=26.0,
                variance_status=VarianceStatus.NORMAL,
                last_heartbeat=now,
            ),
        ]
        for reg in defaults_regs:
            self.save_regulator_health(reg)

        defaults_incidents = [
            IncidentRecord(
                incident_id="inc-critical-trip-501",
                regulator_id="reg-line-4",
                severity=SeverityLevel.CRITICAL,
                trip_reason="Pressure-flow divergence detected",
                root_cause_summary="Automated trip due to correlation divergence",
                triggered_at=now,
                status=IncidentStatus.OPEN,
                pre_trip_telemetry_ref="gs://telemetry/inc-critical-trip-501.json",
            ),
            IncidentRecord(
                incident_id="inc-critical-trip-502",
                regulator_id="reg-line-4",
                severity=SeverityLevel.CRITICAL,
                trip_reason="Sensor variance freeze detected on Oxygen regulator",
                root_cause_summary="Automated trip due to frozen variance signal",
                triggered_at=now,
                status=IncidentStatus.ACKNOWLEDGED,
                pre_trip_telemetry_ref="gs://telemetry/inc-critical-trip-502.json",
            ),
            IncidentRecord(
                incident_id="inc-uuid-1001",
                regulator_id="reg-line-4",
                severity=SeverityLevel.CRITICAL,
                trip_reason="Critical pressure-flow divergence trip on line 4",
                root_cause_summary="Automated trip due to correlation divergence",
                triggered_at=now,
                status=IncidentStatus.OPEN,
                pre_trip_telemetry_ref="gs://telemetry/inc-uuid-1001.json",
            ),
        ]
        for inc in defaults_incidents:
            self.save_incident(inc)
