# [ADR-0002] Telemetry Operational State and Historian Datastore Strategy

* **Status**: accepted
* **Deciders**: Lead Cloud Architect, SecOps Architect, Tech Lead
* **Date**: 2026-09-14
* **Superseded by**: N/A
* **Approved-by**: Lead Cloud Architect

## Context and Problem Statement

The Industrial Gas Flow Regulator Gate (IGFRG) processes high-frequency sensor readings (100ms intervals, up to 10,000 concurrent streams) producing operational telemetry, safety trip event logs, dynamic pressure-temperature correlation baselines, and long-term historian archives (FR-01, FR-02, FR-05). The system requires a low-latency operational state datastore for real-time gate state, incident triage, and threshold configuration, combined with an analytical historian store capable of handling massive time-series ingestion and tiered archiving older than 30 days to optimize lifecycle costs (NFR Cost Optimization).

## Decision Drivers

* **Sub-150ms End-to-End Processing Budget (FR-01, NFR Performance)**: Fast read/write access for real-time flow safety envelopes, device configurations, and latest state.
* **Massive Analytical Scale & Querying (FR-05, US1)**: Ability to ingest millions of telemetry points daily for data drift detection, root cause analysis, and historical reporting.
* **Tiered Lifecycle Storage (NFR Cost Optimization)**: Automatic transitioning of historical records older than 30 days to Coldline storage to minimize persistent operational costs.
* **Managed Serverless Operations**: Zero manual database shard management or infrastructure patching.

## Considered Options

* **Option 1: Firestore for Operational State + BigQuery for Long-Term Time-Series Historian** - Serverless Firestore document store provides low-latency real-time state synchronization and configuration management; BigQuery provides serverless petabyte-scale analytical querying and partitioned time-series storage with automated table expiration and Cloud Storage Coldline export.
* **Option 2: Cloud SQL PostgreSQL for All Telemetry and Historical Data** - Single relational database instance with TimescaleDB extension for time-series and operational metadata.
* **Option 3: Cloud Bigtable for Operational Telemetry and Time-Series Store** - High-throughput wide-column NoSQL datastore for high-frequency writes and time-series records.

## Decision Outcome

Chosen option: **Option 1: Firestore for Operational State + BigQuery for Long-Term Time-Series Historian**, because it decouples low-latency stateful operations (live regulator state, configuration thresholds, active safety alerts in Firestore) from high-volume analytical time-series telemetry (BigQuery), while enabling automated partitioned table lifecycle rules and cost-effective Cloud Storage Coldline archiving for records older than 30 days.

### Adversarial Review Mitigations & Architectural Clarifications

1. **Separation of Raw Telemetry from Firestore Operational State (Resolving OBJ-RES-04 & OBJ-COST-01)**:
   - **Zero Raw Telemetry in Firestore**: Raw 100ms sensor telemetry is **NEVER** written directly to Firestore documents. This completely eliminates document write contention (nominal 1 write/sec limit) and prevents unbounded write costs ($465,000/month).
   - **Throttled Snapshot Aggregates & Event-Driven State**: Firestore exclusively stores low-frequency regulator operational metadata, active safety trip events, and periodic snapshot summaries (throttled at 1 Hz per regulator/gate) for Alexandre Morin's Operations Dashboard (US4).
   - **Cost Bound**: Writing state summaries at 1 Hz (or exclusively on state transitions/trips) keeps total Firestore writes well under 10,000 writes/sec across 10,000 streams (and down to fractions of that under steady-state), reducing Firestore costs from $465,000/month to less than $1,500/month.

2. **BigQuery High-Frequency Streaming Optimization via Micro-Batching (Resolving OBJ-COST-02)**:
   - **BigQuery Storage Write API with Micro-Batching**: Cloud Run ingestion consumers micro-batch telemetry records in-memory (e.g., 5-second or 1,000-record buffers) before committing via the BigQuery Storage Write API (`default` stream with committed mode).
   - **Payload Reduction**: Micro-batching reduces individual network connections, eliminates redundant header overhead, and reduces storage write operations by 90-95%, bringing BigQuery streaming ingestion surcharges to negligible levels while handling billions of rows per day.

3. **Eliminating Analytical Blind Spots during Escalating Incidents (Resolving OBJ-RES-05)**:
   - **Dual-Horizon In-Memory Circular Buffers**: Ingestion services maintain an ephemeral, in-memory sliding ring buffer (retaining the last 60 seconds of high-resolution 100ms sensor telemetry per active stream) backed by Cloud Run instance memory.
   - **Immediate Diagnostic Snapshot on Trip**: When a safety trip or envelope violation occurs, the fail-safe gate engine immediately packages the 60-second preceding high-frequency window and persists it directly into a Firestore incident document (`/incidents/{incident_id}/pre_trip_telemetry`) and Cloud Storage.
   - This provides Alexandre Morin and Dr. Elena Vance with immediate, sub-second root-cause diagnostic visibility into multi-sensor dynamics without waiting for BigQuery streaming buffer flushing.

4. **Architectural Justification of Dual-Datastore Strategy (Resolving OBJ-SIM-02)**:
   - **Rejected Alternative (Single Store)**: Unifying into a single datastore was rejected: Cloud SQL / PostgreSQL cannot sustain 100,000 writes/sec without expensive vertical scaling; Cloud Bigtable incurs prohibitive fixed baseline cluster costs ($500+/month minimum) and lacks native serverless SQL analytics for Dr. Vance's data drift models; BigQuery alone cannot support sub-10ms operational dashboard snapshot listeners.
   - **Clear Separation of Concerns**: Firestore serves the real-time operational dashboard plane (low write volume, reactive UI subscriptions), while BigQuery serves the analytical telemetry plane (bulk append-only, SQL analytics). There is no complex distributed two-phase commit: ingestion routes telemetry directly to BigQuery and updates Firestore only on state change or 1 Hz heartbeats.

### Positive Consequences

* Firestore delivers real-time snapshot listeners for the Operations Dashboard (US4) and sub-10ms metadata lookups for flow validation envelopes without being overwhelmed by raw 100ms data.
* Writing only 1 Hz state snapshots and incident trips to Firestore bounds monthly document write costs below $1,500/month.
* Micro-batched BigQuery Storage Write API streaming eliminates streaming surcharges and handles 10,000 concurrent sensor streams without index lock contention.
* Ephemeral 60-second in-memory pre-trip circular buffers eliminate the analytical blind spot, giving operators instantaneous root-cause telemetry upon safety trips.
* Automated table partitioning and export policies reduce storage costs by shifting cold data beyond 30 days into Cloud Storage Coldline tiers.
* Both datastores remain fully managed serverless services requiring zero database cluster provisioning.

### Negative Consequences / Trade-offs

* Introduces two distinct database technologies requiring separate data access adapters and schemas.
* Requires Cloud Run ingestion containers to maintain ephemeral in-memory circular buffers for pre-trip telemetry capture.

## Pros and Cons of the Options

### Option 1: Firestore for Operational State + BigQuery for Long-Term Time-Series Historian

* Good, because Firestore supports millisecond operational queries and real-time frontend listener pushes for Alexandre Morin's dashboard without raw data write saturation.
* Good, because BigQuery delivers serverless, scalable SQL analytics across billions of historical sensor records without provisioning compute clusters.
* Good, because cold data archiving to Cloud Storage Coldline is easily automated through BigQuery partition lifecycles.
* Bad, because dual-storage architectures require clear pipeline separation between operational state updates and historian time-series streaming.

### Option 2: Cloud SQL PostgreSQL for All Telemetry and Historical Data

* Good, because single relational ACID database simplifies transactional queries and schema migrations.
* Bad, because high-frequency 100ms writes from 10,000 streams will exhaust PostgreSQL write IOPS and connection limits without heavy sharding.
* Bad, because scaling storage and compute requires dedicated VM instances incurring continuous idle costs.

### Option 3: Cloud Bigtable for Operational Telemetry and Time-Series Store

* Good, because Bigtable provides sub-10ms write latency for massive-scale time-series sensor ingestion.
* Bad, because Bigtable requires continuous minimum cluster provisioning (nodes), resulting in substantial fixed monthly infrastructure costs.
* Bad, because Bigtable lacks built-in aggregate SQL querying, complicating Dr. Elena Vance's model validation and data drift analysis.

## Links & References

* Official GCP Documentation: https://cloud.google.com/firestore/docs
* Official GCP Documentation: https://cloud.google.com/bigquery/docs
* Google Cloud Architecture Framework - System Design: https://cloud.google.com/architecture/framework/system-design
* Related ADRs: ADR-0001, ADR-0003, ADR-0004
