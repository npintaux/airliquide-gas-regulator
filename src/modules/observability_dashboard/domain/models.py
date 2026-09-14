"""Domain models and value objects for the Observability Dashboard subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class GateStatus(str, Enum):
    """Current physical valve gate state."""

    NORMAL_REGULATION = "NORMAL_REGULATION"
    MINIMUM_SAFE_FLOW = "MINIMUM_SAFE_FLOW"
    FAIL_SAFE_HOLD = "FAIL_SAFE_HOLD"
    CLOSE_GATE_LOCKED = "CLOSE_GATE_LOCKED"
    OFFLINE_FALLBACK = "OFFLINE_FALLBACK"


class FleetStatus(str, Enum):
    """Overall fleet operational health status."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


class SeverityLevel(str, Enum):
    """Severity categorization of an operational incident."""

    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class AlertChannel(str, Enum):
    """Target notification channel for dispatching alerts."""

    PAGERDUTY = "PAGERDUTY"
    CLOUD_MONITORING = "CLOUD_MONITORING"
    SMS_SAFETY_OFFICER = "SMS_SAFETY_OFFICER"


class VarianceStatus(str, Enum):
    """Telemetry signal variance evaluation."""

    NORMAL = "NORMAL"
    FROZEN_SUSPECTED = "FROZEN_SUSPECTED"
    ERRATIC = "ERRATIC"


class IncidentStatus(str, Enum):
    """Operational resolution status of an incident."""

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class AlertStatus(str, Enum):
    """Delivery status of an alert notification."""

    DELIVERED = "DELIVERED"
    QUEUED = "QUEUED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RegulatorHealthRecord:
    """Immutable operational snapshot of a single gas regulator gate."""

    regulator_id: str
    zone_id: str
    gate_status: GateStatus
    current_flow_sccm: float
    current_pressure_psi: float
    current_temperature_c: float
    variance_status: VarianceStatus
    last_heartbeat: datetime


@dataclass(frozen=True)
class DashboardHealthSnapshot:
    """Immutable fleet health summary aggregate."""

    status: FleetStatus
    timestamp: datetime
    active_regulators_count: int
    healthy_count: int
    degraded_count: int
    tripped_count: int
    gates: tuple[RegulatorHealthRecord, ...]


@dataclass(frozen=True)
class IncidentRecord:
    """Immutable representation of a safety trip or envelope violation event."""

    incident_id: str
    regulator_id: str
    severity: SeverityLevel
    trip_reason: str
    root_cause_summary: str
    triggered_at: datetime
    status: IncidentStatus
    pre_trip_telemetry_ref: str | None = None


@dataclass(frozen=True)
class AlertDispatchCommand:
    """Command payload requesting notification routing for an incident."""

    incident_id: str
    channel: AlertChannel
    message: str


@dataclass(frozen=True)
class AlertDispatchReceipt:
    """Immutable confirmation receipt of notification dispatch."""

    dispatch_id: str
    incident_id: str
    channel: AlertChannel
    status: AlertStatus
    dispatched_at: datetime
    latency_ms: int
