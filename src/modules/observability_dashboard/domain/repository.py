"""Abstract repository port defining persistence and telemetry access."""

from __future__ import annotations

import abc

from .models import (
    IncidentRecord,
    RegulatorHealthRecord,
    SeverityLevel,
)


class DashboardRepository(abc.ABC):
    """Abstract port for querying regulator telemetry snapshots and incident logs."""

    @abc.abstractmethod
    def get_regulator_health(self, regulator_id: str) -> RegulatorHealthRecord | None:
        """Fetch real-time health record for a specific regulator.

        Args:
            regulator_id: Unique regulator identifier.

        Returns:
            The RegulatorHealthRecord if found, or None if not found.
        """
        ...

    @abc.abstractmethod
    def list_regulator_health(
        self,
        zone_id: str | None = None,
        regulator_id: str | None = None,
    ) -> list[RegulatorHealthRecord]:
        """Query regulator operational snapshots filtered by zone or regulator.

        Args:
            zone_id: Optional zone identifier filter.
            regulator_id: Optional regulator identifier filter.

        Returns:
            List of matching RegulatorHealthRecord instances.
        """
        ...

    @abc.abstractmethod
    def list_incidents(
        self,
        limit: int = 50,
        severity: SeverityLevel | None = None,
        regulator_id: str | None = None,
    ) -> list[IncidentRecord]:
        """Query safety trip incidents matching optional filter criteria.

        Args:
            limit: Maximum count of incidents to retrieve.
            severity: Optional severity filter.
            regulator_id: Optional regulator identifier filter.

        Returns:
            List of matching IncidentRecord instances.
        """
        ...

    @abc.abstractmethod
    def get_incident_by_id(self, incident_id: str) -> IncidentRecord | None:
        """Fetch incident record by unique incident ID.

        Args:
            incident_id: Unique UUID of the incident.

        Returns:
            The IncidentRecord if found, or None if not found.
        """
        ...

    @abc.abstractmethod
    def check_zone_exists(self, zone_id: str) -> bool:
        """Verify whether a given zone exists in the plant topology.

        Args:
            zone_id: Plant zone identifier.

        Returns:
            True if the zone exists, False otherwise.
        """
        ...

    @abc.abstractmethod
    def check_regulator_exists(self, regulator_id: str) -> bool:
        """Verify whether a given regulator ID is registered in the fleet.

        Args:
            regulator_id: Regulator identifier.

        Returns:
            True if the regulator exists, False otherwise.
        """
        ...
