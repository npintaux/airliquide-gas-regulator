# Subsystem Specification: Flow Ingestion Engine (`src/modules/flow_ingestion/`)

> **Status**: `LIVING DESIGN DOCUMENT — Tech-Lead-seeded (Gate 2), implementer-maintained`  
> **Source**: Subsystem Tech Lead (`/lead-decompose`)  
> **Parent Architecture**: [`architecture.md`](file:///home/npintaux/airliquide-gas-regulator/docs/architecture.md)  
> **Business Requirements**: [`docs/PRD.md`](file:///home/npintaux/airliquide-gas-regulator/docs/PRD.md)  
> **Interface Contract**: [`openapi.yaml`](file:///home/npintaux/airliquide-gas-regulator/src/modules/flow_ingestion/openapi.yaml)  
> **Selected Domain Pattern**: `pipeline-reducer`  
> **Target Implementer**: Developer Worker (`/implement`)  
> **Target Verifier**: Independent Test Architect (`/test-architect`)

---

## 1. Domain Scope & Responsibility
* **Subsystem Identifier**: `flow_ingestion`
* **Directory Root**: `src/modules/flow_ingestion/`
* **Domain Purpose**: Provides high-throughput, low-latency telemetry packet ingestion from edge gas sensors (Modbus/MQTT IoT bridge), enforces cryptographic HMAC-SHA256 signature verification, normalizes raw telemetry frames, validates sequence monotonicity and jitter intervals, and dispatches bundled events to Google Cloud Pub/Sub with deterministic ordering keys.
* **Allowed Dependencies**:
  - Google Cloud Pub/Sub (`google-cloud-pubsub` via port adapter)
  - Google Cloud Secret Manager (`google-cloud-secret-manager` via port adapter for HMAC key cache warming)
  - Google Cloud Logging (`google-cloud-logging` for structured audit logs)
* **Encapsulation Rules**: Only public HTTP entrypoints in `src/modules/flow_ingestion/entrypoints/` may be invoked by outside callers. Internal domain models, stage processors, and pipeline runners in `src/modules/flow_ingestion/domain/` are strictly private to this subsystem. External interactions cross abstract base class ports implemented in `src/modules/flow_ingestion/adapters/`.

---

## 2. External Contract & API Schema
* **Interface Definition**: Defined in `src/modules/flow_ingestion/openapi.yaml`.
* **Primary Endpoints**:
  | HTTP Verb | Path | Operation ID | Success Status | Error Statuses |
  |---|---|---|---|---|
  | `POST` | `/v1/telemetry/ingest` | `ingestTelemetry` | `201 Created` | `400 Bad Request`, `401 Unauthorized`, `422 Unprocessable`, `500 Internal Error` |
  | `POST` | `/v1/telemetry/batch` | `ingestTelemetryBatch` | `200 OK` | `400 Bad Request`, `401 Unauthorized`, `422 Unprocessable`, `500 Internal Error` |
  | `GET` | `/v1/health` | `getHealth` | `200 OK` | `400 Bad Request`, `422 Unprocessable`, `500 Internal Error` |

---

## 3. Domain Models & Data Structures
Immutable dataclasses representing telemetry frames, accumulating pipeline contexts, and ingestion outcomes:

```python
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class TelemetryRecord:
    """Immutable normalized telemetry reading."""

    plant_id: str
    regulator_id: str
    sensor_id: str
    sequence_number: int
    timestamp_ns: int
    flow_rate_sccm: float
    pressure_bar: float
    temperature_celsius: float
    status_flags: int


@dataclass(frozen=True)
class PipelineContext:
    """Accumulating context threaded through pipeline transformation stages."""

    stream_id: str
    raw_payload: Mapping[str, Any]
    hmac_signature: str
    key_id: str
    is_replayed: bool
    is_authenticated: bool = False
    records: tuple[TelemetryRecord, ...] = ()
    evaluated_metrics: Mapping[str, float] = field(default_factory=dict)
    dispatched_messages: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestionResult:
    """Terminal outcome of telemetry pipeline execution."""

    status: str
    stream_id: str
    message_ids: tuple[str, ...]
    records_count: int
    processed_at_ns: int
```

---

## 4. Domain Pattern Realization & Business Logic

### Selected Pattern: `pipeline-reducer`
* **Port / Abstract Base Class**: Defined in `src/modules/flow_ingestion/domain/stages/base.py`
  - Defines `PipelineStage(abc.ABC)` requiring property `stage_name -> str` and abstract method `process(context: PipelineContext) -> PipelineContext`.
* **Component Breakdown**:
  | Component ID | Class Name | Target File | PRD User Story & AC | Logic & Conditions |
  |---|---|---|---|---|
  | **C1** | `HmacValidationStage` | `src/modules/flow_ingestion/domain/stages/hmac_validation.py` | US-1 (AC-1.1), US-5 (AC-134) | Verifies HMAC-SHA256 signature using cached secret keys from `KeyCachePort`. Rejects invalid or expired signatures with `SignatureVerificationError`. |
  | **C2** | `FrameNormalizationStage` | `src/modules/flow_ingestion/domain/stages/frame_normalization.py` | US-1 (AC-1.1, AC-1.2) | Parses raw input dictionary (single or 10-frame array) into immutable `TelemetryRecord` instances; validates numerical limits and field constraints. |
  | **C3** | `RateJitterEvaluationStage` | `src/modules/flow_ingestion/domain/stages/rate_jitter.py` | US-1 (AC-1.1, AC-1.3), US-5 (AC-136) | Verifies monotonic sequence numbers and delta timestamp intervals (100ms ± jitter tolerance). Tags replayed or out-of-order packets. |
  | **C4** | `PubSubBundleDispatchStage` | `src/modules/flow_ingestion/domain/stages/pubsub_dispatch.py` | US-1 (AC-1.4), US-5 (AC-137) | Packages normalized frames into 1-second Pub/Sub bundles formatted with ordering key `plant_id:regulator_id:sensor_id` and publishes via `PublisherPort`. |

---

## 5. Composite Engine / Coordinator (`stages/base.py` & `pipeline.py`)
* **Base Stage Contract**: `src/modules/flow_ingestion/domain/stages/base.py`
  - Implements `PipelineStage(abc.ABC)`.
* **Coordinator File**: `src/modules/flow_ingestion/domain/pipeline.py`
  - Implements `TelemetryPipelineRunner` executing registered `PipelineStage` instances sequentially over an initial `PipelineContext`.
* **Execution Semantics**:
  1. Sequential ordered stage transformation: `HmacValidationStage` $\to$ `FrameNormalizationStage` $\to$ `RateJitterEvaluationStage` $\to$ `PubSubBundleDispatchStage`.
  2. Each stage yields a new frozen `PipelineContext`.
  3. Immediate fail-fast: if any stage encounters invalid signatures, malformed data, or unrecoverable sequencing violations, a typed domain exception is raised immediately to halt the pipeline.

---

## 6. Error Taxonomy & Status Code Mapping
| Exception Class | HTTP Status Code | Response Code String | Trigger Scenario |
|---|---|---|---|
| `MalformedPayloadError` | `400 Bad Request` | `MALFORMED_PAYLOAD` | Missing required JSON keys, empty frame array, or invalid data types |
| `SignatureVerificationError` | `401 Unauthorized` | `INVALID_SIGNATURE` | HMAC-SHA256 signature mismatch or unrecognized key identifier |
| `SequenceDiscontinuityError` | `422 Unprocessable` | `SEQUENCE_DISCONTINUITY` | Non-monotonic sequence number detected on live telemetry stream |
| `JitterThresholdExceededError` | `422 Unprocessable` | `JITTER_THRESHOLD_EXCEEDED` | Timestamp variance violates allowable 100ms timing window |
| `RateLimitExceededError` | `422 Unprocessable` | `RATE_LIMIT_EXCEEDED` | Stream ingestion frequency exceeds provisioned burst limits |
| `PublisherUnavailableError` | `500 Server Error` | `PUBLISHER_UNAVAILABLE` | Downstream Pub/Sub client failure, network timeout, or connection dropped |
| `InternalIngestionError` | `500 Server Error` | `INTERNAL_INGESTION_ERROR` | Unexpected unhandled exception during pipeline execution |

---

## 7. Acceptance Criteria & Test Cases for Verification
The Independent Test Architect (`/test-architect`) must implement orthogonal contract tests verifying:
1. **Scenario 1 (Happy Path Single Ingestion)**: Valid signed telemetry payload sent to `/v1/telemetry/ingest` returns `201 Created` with `status: accepted` and a valid `message_id`.
2. **Scenario 2 (Happy Path Micro-Batch Ingestion)**: Valid 10-frame 1-second bundle sent to `/v1/telemetry/batch` returns `200 OK` with `frames_accepted: 10` and matching `stream_id`.
3. **Scenario 3 (HMAC Authentication Failure)**: Tampered payload or invalid signature sent to `/v1/telemetry/ingest` or `/v1/telemetry/batch` returns `401 Unauthorized` with `INVALID_SIGNATURE`.
4. **Scenario 4 (Malformed Request Structure)**: Missing mandatory fields or malformed data types return `400 Bad Request` with `MALFORMED_PAYLOAD`.
5. **Scenario 5 (Sequence / Rate Violation)**: Out-of-order sequence frame or extreme timing jitter returns `422 Unprocessable` with `SEQUENCE_DISCONTINUITY` or `JITTER_THRESHOLD_EXCEEDED`.
6. **Scenario 6 (Offline Replay Handling)**: Payload with `is_replayed: true` and backlogged timestamps routes smoothly to historian publication without flagging false sequence alerts.
7. **Scenario 7 (Publisher Dependency Failure)**: Injected failure in the Pub/Sub adapter returns `500 Internal Error` without leaking stack traces or internal secrets.
8. **Scenario 8 (Health Check Endpoint)**: `GET /v1/health` returns `200 OK` with subsystem status, Pub/Sub connection state, and key cache validity.
