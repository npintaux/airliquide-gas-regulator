"""Domain models and value objects for the Fail-Safe Gate subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TelemetryData:
    """Immutable single-point industrial gas telemetry frame."""

    sensor_id: str
    flow_rate: float
    pressure: float
    temperature: float
    timestamp_ns: int


@dataclass(frozen=True)
class EvaluationRequest:
    """Immutable input payload for fail-safe gate rule evaluation."""

    request_id: str
    regulator_id: str
    telemetry: TelemetryData
    recent_history: tuple[TelemetryData, ...] = ()
    operating_mode: str = "normal"


@dataclass(frozen=True)
class Decision:
    """Immutable decision output emitted by rules and the decision engine."""

    is_allowed: bool
    status_code: int
    rule_id: str
    reason: str
    trip_required: bool = False
    violating_rule_id: str | None = None
    diagnostics: dict[str, Any] | None = None


@dataclass(frozen=True)
class ActuatorCommand:
    """Immutable command dispatched to physical regulator hardware."""

    command_id: str
    regulator_id: str
    target_state: str  # closed, safe_hold, minimum_safe_flow, physical_bypass
    reason: str
    initiated_by: str
    timeout_ms: int = 50


@dataclass(frozen=True)
class ActuatorResult:
    """Immutable outcome of hardware actuation."""

    command_id: str
    regulator_id: str
    executed_state: str
    actuation_latency_ms: float
    success: bool
    message: str = ""


@dataclass(frozen=True)
class AdversarialScenario:
    """Immutable scenario specification for CI/CD adversarial testing."""

    scenario_id: str
    anomaly_type: str  # flow_spike, vacuum_drop, noisy_turbulence, frozen_sensor, pressure_disconnect
    duration_ms: int
    injection_magnitude: float


@dataclass(frozen=True)
class ScenarioResult:
    """Result of an individual adversarial scenario run."""

    scenario_id: str
    passed: bool
    reaction_latency_ms: float
    entered_safe_state: bool
    failure_reason: str | None = None


@dataclass(frozen=True)
class GateStatus:
    """Immutable snapshot of the fail-safe gate operational status."""

    regulator_id: str
    valve_state: str
    operational_mode: str
    offline_buffer_used_bytes: int
    offline_buffer_capacity_bytes: int
    last_heartbeat_timestamp_ns: int
    last_trip_reason: str | None = None
    last_trip_timestamp_ns: int | None = None
