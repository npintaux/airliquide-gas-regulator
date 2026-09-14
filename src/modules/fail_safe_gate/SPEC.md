# Subsystem Specification: Fail-Safe Gate & Quality Engine (`src/modules/fail_safe_gate/`)

> **Status**: `LIVING DESIGN DOCUMENT — Tech-Lead-seeded (Gate 2), implementer-maintained`  
> **Source**: Subsystem Tech Lead (`/lead-decompose`)  
> **Parent Architecture**: [`architecture.md`](file:///home/npintaux/airliquide-gas-regulator/docs/architecture.md)  
> **Business Requirements**: [`docs/PRD.md`](file:///home/npintaux/airliquide-gas-regulator/docs/PRD.md)  
> **Interface Contract**: [`openapi.yaml`](file:///home/npintaux/airliquide-gas-regulator/src/modules/fail_safe_gate/openapi.yaml)  
> **Selected Domain Pattern**: `decision-list`  
> **Target Implementer**: Developer Worker (`/implement`)  
> **Target Verifier**: Independent Test Architect (`/test-architect`)

---

## 1. Domain Scope & Responsibility

* **Subsystem Identifier**: `fail_safe_gate`
* **Directory Root**: `src/modules/fail_safe_gate/`
* **Domain Purpose**: The Fail-Safe Gate & Quality Engine evaluates high-frequency industrial gas telemetry against static threshold bounds, dynamic multi-variable pressure-temperature correlation envelopes, and sensor variance/freeze anomalies. In production edge environments, it serves as the sole actuator authority with sub-50ms deterministic close-gate/safe-hold hardware interrupt dispatching. In CI/CD pipelines, it executes automated adversarial simulations injecting synthetic flow spikes, vacuum drops, and turbulence before candidate control algorithms are promoted. During WAN disconnects, it manages offline fallback caching within bounded circular buffers and priority-tiered retention.
* **Allowed Dependencies**: Google Cloud Pub/Sub, Google Cloud Firestore, Google Cloud Monitoring, standard library Python (`abc`, `dataclasses`, `typing`, `math`).
* **Encapsulation Rules**: Only public entrypoints in `src/modules/fail_safe_gate/entrypoints/` may be invoked by outside callers or network endpoints. Internal domain models, rule implementations (`rules/base.py`, rule subclasses), and coordination logic (`engine.py`) in `src/modules/fail_safe_gate/domain/` are strictly private to this subsystem. Hardware actuator communication and offline persistence are mediated strictly through abstract ports implemented in `src/modules/fail_safe_gate/adapters/`.

---

## 2. External Contract & API Schema

* **Interface Definition**: Defined in [`openapi.yaml`](file:///home/npintaux/airliquide-gas-regulator/src/modules/fail_safe_gate/openapi.yaml).
* **Primary Endpoints**:
  | HTTP Verb | Path | Operation ID | Success Status | Error Statuses |
  |---|---|---|---|---|
  | `POST` | `/v1/gate/evaluate` | `evaluateTelemetry` | `200 OK` | `400 Bad Request`, `422 Unprocessable`, `500 Internal Error` |
  | `POST` | `/v1/gate/close` | `closeGate` | `200 OK` | `400 Bad Request`, `422 Unprocessable`, `500 Internal Error` |
  | `POST` | `/v1/gate/simulate` | `simulateAdversarial` | `200 OK` | `400 Bad Request`, `422 Unprocessable`, `500 Internal Error` |
  | `GET` | `/v1/gate/status` | `getGateStatus` | `200 OK` | `400 Bad Request`, `422 Unprocessable`, `500 Internal Error` |

---

## 3. Domain Models & Data Structures

Immutable dataclasses representing telemetry frames, evaluation requests, decisions, and hardware commands:

```python
from dataclasses import dataclass
from typing import Any, Optional


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
    diagnostics: Optional[dict[str, Any]] = None


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
    anomaly_type: (
        str  # flow_spike, vacuum_drop, noisy_turbulence, frozen_sensor
    )
    duration_ms: int
    injection_magnitude: float


@dataclass(frozen=True)
class ScenarioResult:
    """Result of an individual adversarial scenario run."""

    scenario_id: str
    passed: bool
    reaction_latency_ms: float
    entered_safe_state: bool
    failure_reason: Optional[str] = None
```

---

## 4. Domain Pattern Realization & Business Logic

### Selected Pattern: `decision-list`

The primary computational shape of the Fail-Safe Gate is a prioritized linear decision list (Rules Engine). Incoming telemetry is evaluated sequentially against discrete, single-responsibility `Rule` subclasses. If any rule detects an envelope boundary violation or sensor anomaly, it short-circuits the pipeline with a tripping `Decision`, preventing dangerous actuation and triggering an immediate hardware interrupt when required.

* **Port / Abstract Base Class**: Defined in `src/modules/fail_safe_gate/domain/rules/base.py`.
* **Concrete Domain Files**:
  - Base Rule Class: `src/modules/fail_safe_gate/domain/rules/base.py`
  - Coordinator Engine: `src/modules/fail_safe_gate/domain/engine.py`

### Rule ABC Definition (`src/modules/fail_safe_gate/domain/rules/base.py`)

```python
import abc
from ..models import Decision, EvaluationRequest


class Rule(abc.ABC):
    """Abstract Base Class for individual fail-safe gate evaluation predicates."""

    @property
    @abc.abstractmethod
    def rule_id(self) -> str:
        """Unique rule identifier (e.g., 'R-STATIC-01', 'R-CORR-02')."""
        ...

    @abc.abstractmethod
    def evaluate(self, request: EvaluationRequest) -> Decision:
        """Evaluate telemetry against rule criteria. Returns Decision."""
        ...
```

### Component Breakdown

| Component ID | Class Name | Target File | PRD User Story & AC | Logic & Conditions |
|---|---|---|---|---|
| **C1** | `StaticEnvelopeRule` | `src/modules/fail_safe_gate/domain/rules/static_envelope.py` | US-1 (AC-1.2) | Validates flow rate against absolute static safety bounds (e.g. min 0.0, max 1200.0 Sm3/h). Emits trip decision (`422`) if flow exceeds operational safety boundaries. |
| **C2** | `PressureTempCorrelationRule` | `src/modules/fail_safe_gate/domain/rules/pressure_temp_correlation.py` | US-1 (AC-1.3) | Cross-checks flow rate against expected thermodynamic gas law envelopes based on secondary line pressure and temperature. Detects sensor drift; emits trip (`422`) if correlation residual exceeds 3-sigma tolerance. |
| **C3** | `SensorVarianceFreezeRule` | `src/modules/fail_safe_gate/domain/rules/sensor_variance_freeze.py` | US-2 (AC-2.2) | Evaluates `recent_history` sliding window (minimum 5 samples) to verify signal variance. Trips (`422`) if variance is zero across active intervals (frozen telemetry) or if timestamp gap exceeds 250ms (missing heartbeat). |
| **C4** | `FailSafeActuatorPort` | `src/modules/fail_safe_gate/domain/ports/actuator_port.py` | US-2 (AC-2.1, AC-2.3) | Abstract hardware actuator interface with `dispatch_trip(command)` enforcing sub-50ms execution deadline to engage physical bypass or safe-hold valve position. |
| **C5** | `OfflineBufferPort` | `src/modules/fail_safe_gate/domain/ports/buffer_port.py` | US-5 (AC-5.1, AC-5.2, AC-5.3) | Abstract circular ring buffer storage interface for offline fallback mode, enforcing 2GB cap and priority-tiered shedding (Tier 1 trip events retained, Tier 3 nominal telemetry downsampled). |
| **C6** | `AdversarialSimulator` | `src/modules/fail_safe_gate/domain/simulator.py` | US-3 (AC-3.1, AC-3.2, AC-3.3) | Injects synthetic perturbations (flow spikes, vacuum conditions, noisy turbulence) into candidate regulator decision engine in CI/CD pipeline, verifying trip within 50ms window. |

---

## 5. Composite Engine / Coordinator (`engine.py`)

* **Coordinator File**: `src/modules/fail_safe_gate/domain/engine.py`
* **Composition Pattern**: Instantiates and coordinates ordered sequence of `Rule` implementations with optional short-circuiting on trip violation.

```python
from collections.abc import Sequence
from .models import Decision, EvaluationRequest
from .ports.actuator_port import FailSafeActuatorPort
from .rules.base import Rule


class DecisionEngine:
    """Composed dispatcher executing ordered rule sequence with short-circuiting."""

    def __init__(
        self,
        rules: Sequence[Rule],
        actuator_port: FailSafeActuatorPort | None = None,
    ) -> None:
        self._rules = tuple(rules)
        self._actuator = actuator_port

    def evaluate(self, request: EvaluationRequest) -> Decision:
        for rule in self._rules:
            decision = rule.evaluate(request)
            if not decision.is_allowed:
                if decision.trip_required and self._actuator is not None:
                    # Deterministic local trip dispatch within sub-50ms budget
                    self._actuator.dispatch_emergency_trip(
                        regulator_id=request.regulator_id,
                        reason=decision.reason,
                    )
                return decision

        return Decision(
            is_allowed=True,
            status_code=200,
            rule_id="PASS",
            reason="Telemetry passed all safety envelope and correlation checks.",
            trip_required=False,
        )
```

* **Execution Semantics**:
  1. Rules execute in deterministic order: `StaticEnvelopeRule` -> `PressureTempCorrelationRule` -> `SensorVarianceFreezeRule`.
  2. First failing rule immediately short-circuits evaluation.
  3. If `trip_required` is `True`, local hardware interrupt is dispatched via `FailSafeActuatorPort` before returning the response.

---

## 6. Error Taxonomy & Status Code Mapping

| Exception / Error Condition | HTTP Status Code | Response Code String | Trigger Scenario |
|---|---|---|---|
| `InvalidPayloadError` | `400 Bad Request` | `INVALID_PAYLOAD` | Missing required fields, invalid types, or negative temperature/pressure values |
| `SafetyEnvelopeViolation` | `422 Unprocessable` | `ENVELOPE_TRIP` | Flow rate exceeds upper/lower static safety threshold (US-1) |
| `CorrelationDriftViolation` | `422 Unprocessable` | `CORRELATION_DRIFT` | Pressure-temperature thermodynamic correlation residual exceeds tolerance (US-1) |
| `SensorFreezeDetected` | `422 Unprocessable` | `SENSOR_FROZEN` | Zero variance detected across sliding window or missing heartbeat interval (US-2) |
| `ActuationInterlockConflict` | `422 Unprocessable` | `INTERLOCK_CONFLICT` | Actuator command cannot be executed due to physical interlock state |
| `HardwareCommunicationError` | `500 Server Error` | `ACTUATOR_COMM_ERROR` | Modbus/fieldbus communication failure during interrupt dispatch |
| `InternalServiceError` | `500 Server Error` | `INTERNAL_ERROR` | Unhandled internal exception or memory exhaustion |

---

## 7. Acceptance Criteria & Test Cases for Verification

The Independent Test Architect (`/test-architect`) must implement orthogonal contract tests verifying:

1. **Scenario 1 (Happy Path - Nominal Flow Evaluation)**:
   - Valid telemetry (flow=450.0 Sm3/h, pressure=12.5 bar, temperature=293.15 K) evaluated.
   - Response: `200 OK`, `is_allowed=True`, `trip_required=False`.
2. **Scenario 2 (Static Envelope Trip - Out of Range)**:
   - Telemetry with flow=1500.0 Sm3/h (exceeding 1200.0 threshold) evaluated.
   - Response: `422 Unprocessable`, `is_allowed=False`, `trip_required=True`, `violating_rule_id="R-STATIC-01"`.
3. **Scenario 3 (Dynamic Pressure-Temperature Drift)**:
   - Flow reading deviates from pressure-temperature correlation envelope.
   - Response: `422 Unprocessable`, `is_allowed=False`, `trip_required=True`, `violating_rule_id="R-CORR-02"`.
4. **Scenario 4 (Sensor Freeze & Heartbeat Loss)**:
   - Recent history array contains identical flow and pressure readings over 10 consecutive ticks (zero variance).
   - Response: `422 Unprocessable`, `violating_rule_id="R-VAR-03"`, `reason` cites sensor freeze.
5. **Scenario 5 (Hardware Fail-Safe Actuation Sub-50ms)**:
   - POST to `/v1/gate/close` with `target_state: "closed"`.
   - Response: `200 OK`, `actuation_latency_ms < 50.0`, `success=True`.
6. **Scenario 6 (Adversarial CI/CD Simulation Gate)**:
   - POST to `/v1/gate/simulate` with synthetic turbulence and vacuum drop scenarios.
   - Candidate logic entering safe state within 50ms returns `200 OK` with `overall_verdict: "passed"`.
   - Logic failing to trip within 50ms returns `422 Unprocessable` with `overall_verdict: "rejected"`.
7. **Scenario 7 (Validation Error Handling)**:
   - POST to `/v1/gate/evaluate` with missing fields or negative pressure.
   - Response: `400 Bad Request` with structured `ErrorResponse`.
8. **Scenario 8 (Gate Status & Offline Buffer Telemetry)**:
   - GET `/v1/gate/status` returns `200 OK` with valve state, buffer utilization bytes, and capacity.
