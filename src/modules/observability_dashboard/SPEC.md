# Subsystem Specification: Observability Dashboard & Alerting (`src/modules/observability_dashboard/`)

> **Status**: `LIVING DESIGN DOCUMENT — Tech-Lead-seeded (Gate 2), implementer-maintained`  
> **Source**: Subsystem Tech Lead (`/lead-decompose`)  
> **Parent Architecture**: [`architecture.md`](file:///home/npintaux/airliquide-gas-regulator/docs/architecture.md)  
> **Business Requirements**: [`docs/PRD.md`](file:///home/npintaux/airliquide-gas-regulator/docs/PRD.md)  
> **Interface Contract**: [`openapi.yaml`](file:///home/npintaux/airliquide-gas-regulator/src/modules/observability_dashboard/openapi.yaml)  
> **Selected Domain Pattern**: `repository-service`  
> **Target Implementer**: Developer Worker (`/implement`)  
> **Target Verifier**: Independent Test Architect (`/test-architect`)

---

## 1. Domain Scope & Responsibility
* **Subsystem Identifier**: `observability_dashboard`
* **Directory Root**: `src/modules/observability_dashboard/`
* **Domain Purpose**: Provides centralized, real-time observability across the fleet of Industrial Gas Flow Regulator Gates (IGFRG). Aggregates operational state snapshots from Firestore, retrieves incident logs and pre-trip 60-second telemetry windows, runs automated root cause summaries, queries historical time-series drift metrics from BigQuery, and routes critical incident notifications to on-call engineering channels (PagerDuty, Cloud Monitoring) within the sub-60-second budget.
* **Allowed Dependencies**:
  - Google Cloud Firestore (`roles/datastore.viewer`)
  - Google Cloud BigQuery (`roles/bigquery.dataViewer`, `roles/bigquery.jobUser`)
  - Google Cloud Monitoring & Cloud Logging (`roles/monitoring.viewer`)
  - Identity-Aware Proxy (IAP) context headers
* **Encapsulation Rules**: Only public entrypoints in `src/modules/observability_dashboard/entrypoints/` may be invoked by outside callers. Internal domain models and logic in `src/modules/observability_dashboard/domain/` are strictly private to this subsystem. External interactions are mediated via ports in `repository.py` and realized in `src/modules/observability_dashboard/adapters/`.

---

## 2. External Contract & API Schema
* **Interface Definition**: Defined in [`src/modules/observability_dashboard/openapi.yaml`](file:///home/npintaux/airliquide-gas-regulator/src/modules/observability_dashboard/openapi.yaml).
* **Primary Endpoints**:
  | HTTP Verb | Path | Operation ID | Success Status | Error Statuses | Description |
  |---|---|---|---|---|---|
  | `GET` | `/v1/dashboard/health` | `getDashboardHealth` | `200 OK` | `400 Bad Request`, `404 Not Found`, `500 Server Error` | Fleet flow health, gate status, and variance checks |
  | `GET` | `/v1/dashboard/incidents` | `getIncidentLogs` | `200 OK` | `400 Bad Request`, `404 Not Found`, `500 Server Error` | Safety trip incident triage and root cause summaries |
  | `POST` | `/v1/dashboard/alerts` | `dispatchAlertNotification` | `201 Created` | `400 Bad Request`, `404 Not Found`, `500 Server Error` | Dispatch emergency alert to on-call engineers (<60s) |

---

## 3. Domain Models & Data Structures
Immutable dataclasses representing operational entities, snapshot queries, incident summaries, and alert records:

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class GateStatus(str, Enum):
    NORMAL_REGULATION = "NORMAL_REGULATION"
    MINIMUM_SAFE_FLOW = "MINIMUM_SAFE_FLOW"
    FAIL_SAFE_HOLD = "FAIL_SAFE_HOLD"
    CLOSE_GATE_LOCKED = "CLOSE_GATE_LOCKED"
    OFFLINE_FALLBACK = "OFFLINE_FALLBACK"


class FleetStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


class SeverityLevel(str, Enum):
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class AlertChannel(str, Enum):
    PAGERDUTY = "PAGERDUTY"
    CLOUD_MONITORING = "CLOUD_MONITORING"
    SMS_SAFETY_OFFICER = "SMS_SAFETY_OFFICER"


@dataclass(frozen=True)
class RegulatorHealthRecord:
    """Immutable operational snapshot of a single gas regulator gate."""

    regulator_id: str
    zone_id: str
    gate_status: GateStatus
    current_flow_sccm: float
    current_pressure_psi: float
    current_temperature_c: float
    variance_status: str
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
    status: str
    pre_trip_telemetry_ref: Optional[str] = None


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
    status: str
    dispatched_at: datetime
    latency_ms: int
```

---

## 4. Domain Pattern Realization & Business Logic

### Selected Pattern: `repository-service`
* **Port / Abstract Base Class**: Defined in `src/modules/observability_dashboard/domain/repository.py`
* **Domain Coordinator**: Defined in `src/modules/observability_dashboard/domain/service.py`
* **Pattern Justification**: The subsystem functions primarily as an operational query, data retrieval, and dispatch orchestration engine. It reads aggregated 1 Hz regulator state documents from Firestore, queries historical telemetry from BigQuery, and writes notification dispatches. There is no multi-step state machine lifecycle or complex chained rule predicate tree. The clean separation between the domain service (`DashboardService`) and data persistence ports (`DashboardRepository`, `AlertDispatchPort`) enables isolated testing with in-memory fakes while cleanly integrating with Firestore and BigQuery in production.

### Concrete Pattern Domain Files:
1. `src/modules/observability_dashboard/domain/repository.py`: Declares abstract repository port `DashboardRepository`.
2. `src/modules/observability_dashboard/domain/alert_dispatcher.py`: Declares abstract outbound port `AlertDispatchPort` (separated to enforce 1-class-per-file).
3. `src/modules/observability_dashboard/domain/service.py`: Coordinates fleet health aggregation, incident query filtering, root-cause enrichment, and SLA-bounded alert dispatching.

### Component Breakdown & PRD Mapping:
| Component ID | Class Name | Target File | PRD User Story & AC | Logic & Conditions |
|---|---|---|---|---|
| **C1** | `DashboardRepository` | `src/modules/observability_dashboard/domain/repository.py` | US-4 (AC-4.1, AC-4.2) | Abstract port defining `get_regulator_health()`, `list_regulator_health()`, `check_zone_exists()`, `check_regulator_exists()`, `list_incidents()`, and `get_incident_by_id()`. Decouples Firestore and BigQuery queries. |
| **C2** | `AlertDispatchPort` | `src/modules/observability_dashboard/domain/alert_dispatcher.py` | US-4 (AC-4.3) | Abstract outbound port defining `dispatch_alert(command)` to PagerDuty or Cloud Monitoring notification sinks. |
| **C3** | `DashboardService` | `src/modules/observability_dashboard/domain/service.py` | US-4 (AC-4.1, AC-4.2, AC-4.3) | Domain coordinator that aggregates fleet health statuses, performs incident filtering, validates triage rules, verifies incident existence prior to alert dispatch, and enforces latency budgets. |
| **C4** | `RootCauseSummarizer` | `src/modules/observability_dashboard/domain/summarizer.py` | US-4 (AC-4.2) | Synthesizes automated, deterministic root-cause diagnosis text from trip telemetry attributes (e.g. pressure-flow divergence, zero variance detection, threshold breach). |

---

## 5. Composite Engine / Coordinator (`service.py`)
* **Coordinator File**: `src/modules/observability_dashboard/domain/service.py`
* **Composition Pattern**:
  `DashboardService` is initialized with dependencies conforming to `DashboardRepository` and `AlertDispatchPort`:
  ```python
  class DashboardService:
      def __init__(
          self,
          repository: DashboardRepository,
          alert_dispatcher: AlertDispatchPort,
      ) -> None:
          self._repository = repository
          self._alert_dispatcher = alert_dispatcher
  ```
* **Execution Semantics**:
  1. `resolve_health(zone_id, regulator_id)`:
     - Queries repository for regulator state records.
     - Validates zone and regulator existence; raises `ResourceNotFoundError` if filter specifies non-existent target.
     - Computes aggregated fleet health metrics (`healthy_count`, `degraded_count`, `tripped_count`, `status`).
  2. `resolve_incidents(limit, severity, regulator_id)`:
     - Validates query bounds (`1 <= limit <= 200`); raises `InvalidFilterError` for invalid parameters.
     - Verifies regulator exists if `regulator_id` is supplied.
     - Fetches incident records, enriches with root cause summary if absent, and returns sorted by `triggered_at` descending.
  3. `dispatch_alert(command)`:
     - Validates command payload; raises `InvalidPayloadError` on empty fields.
     - Confirms incident exists via `repository.get_incident_by_id(command.incident_id)`; raises `IncidentNotFoundError` if missing.
     - Invokes `alert_dispatcher.dispatch_alert(command)`.
     - Validates dispatch elapsed latency; raises `DispatchTimeoutError` if routing exceeds 60,000ms SLA budget.
     - Returns immutable `AlertDispatchReceipt`.

---

## 6. Error Taxonomy & Status Code Mapping
| Exception Class | HTTP Status Code | Response Code String | Trigger Scenario |
|---|---|---|---|
| `InvalidPayloadError` | `400 Bad Request` | `INVALID_PAYLOAD` | Missing required fields in alert dispatch or malformed body |
| `InvalidFilterError` | `400 Bad Request` | `INVALID_FILTER` | Limit out of bounds (<1 or >200) or invalid severity enum |
| `ResourceNotFoundError` | `404 Not Found` | `RESOURCE_NOT_FOUND` | Specified `regulator_id` or `zone_id` does not exist |
| `IncidentNotFoundError` | `404 Not Found` | `INCIDENT_NOT_FOUND` | Referenced `incident_id` in alert dispatch not found |
| `AlertDispatchError` | `500 Server Error` | `ALERT_DISPATCH_FAILED` | Downstream notification gateway (PagerDuty) communication failure |
| `StorageUnavailableError` | `500 Server Error` | `STORAGE_UNAVAILABLE` | Firestore or BigQuery adapter connection drop or query timeout |
| `InternalServiceError` | `500 Server Error` | `INTERNAL_ERROR` | Unexpected unhandled domain exception |

---

## 7. Acceptance Criteria & Test Cases for Verification
The Independent Test Architect (`/test-architect`) must implement orthogonal contract tests verifying:
1. **Scenario 1 (Health Snapshot Happy Path - GET /v1/dashboard/health)**:
   - Request with valid zone or without filters returns `200 OK`.
   - Response contains typed fleet status, counts (`healthy_count`, `degraded_count`, `tripped_count`), and list of regulator gate records matching schema.
2. **Scenario 2 (Incident Query Happy Path - GET /v1/dashboard/incidents)**:
   - Query with `limit=10` and `severity=CRITICAL` returns `200 OK`.
   - Each item includes `incident_id`, `regulator_id`, `root_cause_summary`, `triggered_at`, and `status`.
3. **Scenario 3 (Alert Dispatch Happy Path - POST /v1/dashboard/alerts)**:
   - Valid payload with existing `incident_id` and channel `PAGERDUTY` returns `201 Created`.
   - Response includes `dispatch_id`, `status: DELIVERED`, and `latency_ms <= 60000`.
4. **Scenario 4 (Validation Failure - Bad Request)**:
   - Request to `/v1/dashboard/alerts` with empty fields returns `400 Bad Request` with `INVALID_PAYLOAD`.
   - Query to `/v1/dashboard/incidents?limit=500` returns `400 Bad Request` with `INVALID_FILTER`.
5. **Scenario 5 (Target Not Found - 404)**:
   - Query to `/v1/dashboard/health?regulator_id=non-existent-reg` returns `404 Not Found` with `RESOURCE_NOT_FOUND`.
   - Dispatch to `/v1/dashboard/alerts` referencing an unknown `incident_id` returns `404 Not Found` with `INCIDENT_NOT_FOUND`.
6. **Scenario 6 (Storage / Dispatcher Failure - 500)**:
   - Simulated Firestore outage or unhandled exception returns `500 Server Error` with RFC 7807 structured JSON error code `STORAGE_UNAVAILABLE` or `INTERNAL_ERROR` without leaking stack traces.
