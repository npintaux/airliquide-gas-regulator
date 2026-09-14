"""Domain service coordinating fleet health, incident queries, and alert dispatching."""

from __future__ import annotations

from datetime import UTC, datetime

from .alert_dispatcher import AlertDispatchPort
from .exceptions import (
    DispatchTimeoutError,
    IncidentNotFoundError,
    InvalidFilterError,
    InvalidPayloadError,
    ResourceNotFoundError,
)
from .models import (
    AlertDispatchCommand,
    AlertDispatchReceipt,
    DashboardHealthSnapshot,
    FleetStatus,
    GateStatus,
    IncidentRecord,
    SeverityLevel,
)
from .repository import DashboardRepository
from .summarizer import RootCauseSummarizer

MAX_SLA_LATENCY_MS = 60000


class DashboardService:
    """Domain coordinator for operational observability and incident management."""

    def __init__(
        self,
        repository: DashboardRepository,
        alert_dispatcher: AlertDispatchPort,
        summarizer: RootCauseSummarizer | None = None,
    ) -> None:
        """Initialize the domain service with repository and alert dispatcher.

        Args:
            repository: Port for data persistence and operational queries.
            alert_dispatcher: Port for routing alert notifications.
            summarizer: Optional diagnostic root cause summarizer.
        """
        self._repository = repository
        self._alert_dispatcher = alert_dispatcher
        self._summarizer = summarizer or RootCauseSummarizer()

    def resolve_health(
        self, zone_id: str | None = None, regulator_id: str | None = None
    ) -> DashboardHealthSnapshot:
        """Resolve fleet health snapshot filtered by zone or regulator.

        Args:
            zone_id: Optional industrial zone filter.
            regulator_id: Optional regulator identifier filter.

        Returns:
            Aggregated DashboardHealthSnapshot.

        Raises:
            ResourceNotFoundError: If specified zone or regulator does not exist.
        """
        if zone_id is not None and not self._repository.check_zone_exists(zone_id):
            raise ResourceNotFoundError(f"Zone '{zone_id}' not found.")

        if regulator_id is not None and not self._repository.check_regulator_exists(
            regulator_id
        ):
            raise ResourceNotFoundError(f"Regulator '{regulator_id}' not found.")

        gates = self._repository.list_regulator_health(
            zone_id=zone_id, regulator_id=regulator_id
        )

        healthy_count = 0
        degraded_count = 0
        tripped_count = 0

        for gate in gates:
            if gate.gate_status == GateStatus.NORMAL_REGULATION:
                healthy_count += 1
            elif gate.gate_status in (
                GateStatus.MINIMUM_SAFE_FLOW,
                GateStatus.OFFLINE_FALLBACK,
            ):
                degraded_count += 1
            elif gate.gate_status in (
                GateStatus.FAIL_SAFE_HOLD,
                GateStatus.CLOSE_GATE_LOCKED,
            ):
                tripped_count += 1

        if tripped_count > 0:
            fleet_status = FleetStatus.CRITICAL
        elif degraded_count > 0:
            fleet_status = FleetStatus.DEGRADED
        else:
            fleet_status = FleetStatus.HEALTHY

        return DashboardHealthSnapshot(
            status=fleet_status,
            timestamp=datetime.now(UTC),
            active_regulators_count=len(gates),
            healthy_count=healthy_count,
            degraded_count=degraded_count,
            tripped_count=tripped_count,
            gates=tuple(gates),
        )

    def resolve_incidents(
        self,
        limit: int = 50,
        severity: SeverityLevel | None = None,
        regulator_id: str | None = None,
    ) -> tuple[list[IncidentRecord], int]:
        """Query incident records with validation, sorting, and root-cause enrichment.

        Args:
            limit: Maximum count of incidents to return (1 to 200).
            severity: Optional severity filter.
            regulator_id: Optional regulator filter.

        Returns:
            Tuple of (list of enriched incidents, total matching count).

        Raises:
            InvalidFilterError: If limit is out of bounds [1, 200].
            ResourceNotFoundError: If regulator_id is provided but does not exist.
        """
        if limit < 1 or limit > 200:
            raise InvalidFilterError(f"Limit must be between 1 and 200; got {limit}.")

        if regulator_id is not None and not self._repository.check_regulator_exists(
            regulator_id
        ):
            raise ResourceNotFoundError(f"Regulator '{regulator_id}' not found.")

        raw_incidents = self._repository.list_incidents(
            limit=limit, severity=severity, regulator_id=regulator_id
        )

        enriched: list[IncidentRecord] = []
        for inc in raw_incidents:
            summary = self._summarizer.summarize(
                inc.trip_reason, inc.root_cause_summary
            )
            if summary != inc.root_cause_summary:
                enriched.append(
                    IncidentRecord(
                        incident_id=inc.incident_id,
                        regulator_id=inc.regulator_id,
                        severity=inc.severity,
                        trip_reason=inc.trip_reason,
                        root_cause_summary=summary,
                        triggered_at=inc.triggered_at,
                        status=inc.status,
                        pre_trip_telemetry_ref=inc.pre_trip_telemetry_ref,
                    )
                )
            else:
                enriched.append(inc)

        return enriched, len(enriched)

    def dispatch_alert(self, command: AlertDispatchCommand) -> AlertDispatchReceipt:
        """Validate alert command, confirm incident exists, and route notification.

        Args:
            command: Alert dispatch payload.

        Returns:
            Delivery receipt confirming delivery status and latency.

        Raises:
            InvalidPayloadError: If required fields in command are empty.
            IncidentNotFoundError: If referenced incident does not exist.
            DispatchTimeoutError: If routing exceeds 60s SLA budget.
        """
        if not command.incident_id or not command.incident_id.strip():
            raise InvalidPayloadError("incident_id cannot be empty.")

        if not command.message or not command.message.strip():
            raise InvalidPayloadError("message cannot be empty.")

        incident = self._repository.get_incident_by_id(command.incident_id)
        if incident is None:
            raise IncidentNotFoundError(f"Incident '{command.incident_id}' not found.")

        receipt = self._alert_dispatcher.dispatch_alert(command)

        if receipt.latency_ms > MAX_SLA_LATENCY_MS:
            raise DispatchTimeoutError(
                f"Dispatch exceeded SLA budget: {receipt.latency_ms}ms > {MAX_SLA_LATENCY_MS}ms."
            )

        return receipt
