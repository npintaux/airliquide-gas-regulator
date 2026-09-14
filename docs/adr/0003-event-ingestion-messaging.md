# [ADR-0003] Asynchronous Event Ingestion and Messaging Architecture

* **Status**: accepted
* **Deciders**: Lead Cloud Architect, SecOps Architect, Tech Lead
* **Date**: 2026-09-14
* **Superseded by**: N/A
* **Approved-by**: Lead Cloud Architect

## Context and Problem Statement

The Industrial Gas Flow Regulator Gate (IGFRG) must ingest sensor packets from up to 10,000 concurrent industrial streams transmitting at 100ms intervals (FR-01, NFR Performance). In addition, critical safety violation alerts and root-cause summaries must be dispatched to on-call engineers within 60 seconds (FR-05, NFR Operational Excellence), and pull requests must trigger adversarial simulations in the CI/CD pipeline (FR-03). A direct synchronous HTTP/gRPC coupling between edge gateways and downstream processors risks cascading failure and packet loss during traffic spikes or downstream service degradation. The architecture requires a highly durable, scalable asynchronous messaging bus to decouple edge ingestion, real-time validation, emergency notifications, and historian storage.

## Decision Drivers

* **High-Throughput Concurrent Stream Ingestion (FR-01, NFR Performance)**: Capable of handling bursts across 10,000 sensor streams with sub-150ms total validation latency budget.
* **Guaranteed Delivery & At-Least-Once Semantics (US1, NFR Reliability)**: Zero telemetry packet loss for compliance auditing and historian tracking.
* **Dead-Letter Handling & Fault Isolation**: Unparseable or malformed sensor frames must be segregated into a dead-letter queue without stalling healthy pipelines.
* **Multi-Zone High Availability (NFR Reliability)**: Message bus must operate across at least three availability zones with 99.99% uptime.

## Considered Options

* **Option 1: Google Cloud Pub/Sub with Dead-Letter Topics** - Fully managed global event bus with automatic multi-zone replication, independent topic subscriptions for telemetry processing, incident alerting, and historian ingestion, and native dead-letter queues.
* **Option 2: Self-Managed Apache Kafka on Compute Engine** - Multi-broker Kafka cluster deployed across compute instances with Zookeeper/KRaft for distributed commit logs.
* **Option 3: Google Cloud Tasks** - Managed task queuing service for point-to-point asynchronous task dispatching to HTTP targets.

## Decision Outcome

Chosen option: **Option 1: Google Cloud Pub/Sub with Dead-Letter Topics**, because it provides serverless horizontal scaling, zero maintenance overhead, multi-zone regional durability (99.99% SLA), native push/pull subscriptions to Cloud Run services, and integrated dead-letter queues to isolate malformed sensor packets without blocking production pipelines.

### Adversarial Review Mitigations & Architectural Clarifications

1. **Pub/Sub Stream Ordering Keys & Sequence Validation (Resolving OBJ-RES-06)**:
   - **Enforced Ordering Keys**: Every message published to `telemetry-events` explicitly sets Pub/Sub ordering keys formatted by sensor stream: `ordering_key = f"{plant_id}:{regulator_id}:{sensor_id}"`.
   - **Regional In-Order Delivery**: Pub/Sub guarantees strict FIFO delivery within each individual sensor stream ordering key, eliminating out-of-order telemetry packet delivery to cloud gate evaluators.
   - **Sequence Monotonicity Check**: Consumers check the embedded monotonic frame sequence number; any late-arriving or duplicate packet is safely deduplicated without triggering false frozen-telemetry or rate-of-change safety trips.

2. **Schema Registry, DLQ Alerting, and Drain Monitoring (Resolving OBJ-RES-07)**:
   - **Ingress Schema Pre-Validation**: The Cloud Run ingestion gateway validates all incoming payloads against an Avro/JSON Schema contract before publishing to Pub/Sub. Schema evolution is managed via backwards-compatible versioning.
   - **DLQ Threshold Alerting**: Cloud Monitoring alert policies track `dead-letter-telemetry` message publish rates. If DLQ volume exceeds 5 messages/minute across any stream, an automated P1 incident is raised within 30 seconds to the platform engineering on-call rotation.
   - **Edge Backpressure & Rejection**: Payloads failing schema validation at the HTTP ingress point receive immediate HTTP 422 (Unprocessable Entity) responses with structured diagnostic error codes, alerting edge nodes immediately rather than silently dumping millions of records into a cloud DLQ.

3. **Message Volume Optimization & Edge Payload Aggregation (Resolving OBJ-COST-04)**:
   - **Edge Multi-Frame Aggregation**: Rather than publishing 100,000 raw individual 100ms frames per second to Pub/Sub, edge agents bundle readings into 1-second multi-frame arrays (10 readings per payload per sensor stream).
   - **90% Cost Reduction**: This aggregation reduces Pub/Sub message operations from 260 billion/month down to 26 billion/month, slashing monthly Pub/Sub publishing and subscription delivery costs by ~90% (saving >$9,000/month) while preserving all high-frequency 100ms data resolution within the batched array payload.

4. **Event Bus Decoupling vs In-Memory Synchronous Processing (Resolving OBJ-SIM-01)**:
   - **Safety Separation**: Physical fail-safe shutoff occurs locally on edge hardware within 50ms, completely independent of Pub/Sub. Therefore, Pub/Sub is never in the critical path of physical hardware actuation.
   - **Fan-Out Necessity**: For cloud-side workloads, Pub/Sub decouples the high-throughput HTTP ingress tier from heterogeneous, independently scaling downstream consumers:
     1. BigQuery historian streaming archiver.
     2. Centralized safety alert and anomaly notification pipeline (dispatched within 60s).
     3. Observability Dashboard state updater.
   - Direct synchronous in-memory processing or point-to-point coupling would cause cascading failures if BigQuery streaming experienced transient degradation, causing HTTP ingress thread starvation and dropping live sensor feeds. Pub/Sub provides essential elastic buffering.

### Positive Consequences

* Seamless horizontal scaling effortlessly absorbs traffic spikes from 10,000 concurrent sensor feeds without pre-provisioning broker clusters.
* Ordering keys guarantee deterministic per-sensor FIFO message delivery, preventing false variance anomalies or sequence errors.
* Edge micro-batching into 1-second bundles reduces Pub/Sub operations and associated billing by 90%.
* Ingress schema validation and DLQ threshold alerts prevent silent data loss and detect firmware mismatches within 30 seconds.
* Decouples the flow ingestion pipeline from downstream consumers (fail-safe gate evaluators, BigQuery historian archivers, and dashboard alerting processors).
* Automatic multi-zone replication satisfies the 99.99% availability NFR without requiring manual failover configuration.

### Negative Consequences / Trade-offs

* Pub/Sub ordering keys require all messages for a given key to route to the same partition, which requires careful key distribution (guaranteed by sensor ID granularity).
* Consumers must handle micro-batched arrays containing 10 sequential 100ms readings per message.

## Pros and Cons of the Options

### Option 1: Google Cloud Pub/Sub with Dead-Letter Topics

* Good, because it provides elastic serverless scaling and zero infrastructure management overhead.
* Good, because ordering keys guarantee per-sensor sequence integrity without distributed locks.
* Good, because 1-second edge frame aggregation slashes Pub/Sub operation costs by 90%.
* Good, because native multi-zone distribution ensures high availability and disaster resilience.
* Good, because push subscriptions trigger Cloud Run consumers directly with IAM-authenticated HTTP requests.
* Bad, because consumers must iterate through batched payload arrays and enforce idempotency.

### Option 2: Self-Managed Apache Kafka on Compute Engine

* Good, because Kafka partition keys provide strict message ordering and massive sequential write throughput.
* Bad, because running Kafka brokers requires continuous cluster administration, disk rebalancing, and patch management.
* Bad, because static broker provisioning incurs continuous idle compute costs, violating the cost-optimization pillar.

### Option 3: Google Cloud Tasks

* Good, because Cloud Tasks provides granular rate-limiting and task execution timing controls.
* Bad, because Cloud Tasks is designed for point-to-point worker dispatch rather than fan-out pub/sub streaming across multiple independent subscribers.
* Bad, because throughput limitations make it unsuitable for high-frequency 10,000 stream telemetry fan-out.

## Links & References

* Official GCP Documentation: https://cloud.google.com/pubsub/docs
* Google Cloud Architecture Framework - System Design: https://cloud.google.com/architecture/framework/system-design
* Related ADRs: ADR-0001, ADR-0002, ADR-0004
