# [ADR-0001] Hybrid Edge-Cloud Compute Architecture for Flow Regulation

* **Status**: accepted
* **Deciders**: Lead Cloud Architect, SecOps Architect, Tech Lead
* **Date**: 2026-09-14
* **Superseded by**: N/A
* **Approved-by**: Lead Cloud Architect

## Context and Problem Statement

The Industrial Gas Flow Regulator Gate (IGFRG) requires strict real-time telemetry validation and sub-50ms emergency hardware fail-safe actuation (FR-01, FR-04), while also supporting up to 10,000 concurrent sensor streams, automated adversarial testing during pull request cycles (FR-03, US3), and centralized observability (FR-05). In industrial chemical manufacturing, a network disruption between local plant equipment and cloud infrastructure cannot compromise physical plant safety. The system requires an architectural compute division that guarantees deterministic local safety execution and offline fallback resilience while leveraging serverless cloud compute for scalable validation, adversarial simulation, and analytics.

## Decision Drivers

* **Sub-50ms Hardware Fail-Safe Actuation (FR-04, US2)**: Emergency close-gate or safe-hold triggers must fire deterministically within 50ms upon telemetry violation or sensor stall.
* **Offline Fallback Resilience (US5, NFR Reliability)**: The gate must continue operating in a safe state during complete WAN or cloud network disconnects.
* **Elastic Serverless Scaling (NFR Cost Optimization, US3)**: Ephemeral PR adversarial simulations and high-throughput analytical ingestion must scale down to zero when idle.
* **Operational Simplicity**: Minimize operational maintenance burden across distributed sites while adhering to Google Cloud Well-Architected Framework principles.

## Considered Options

* **Option 1: Hybrid Edge (Local Deterministic Runtime) + Cloud Run (Serverless Regional Ingestion & Testing)** - Deterministic local edge container on plant compute for critical sub-50ms fail-safe actuation and offline fallback; Cloud Run in Google Cloud multi-zone regional deployment for telemetry ingestion, adversarial PR testing, and management.
* **Option 2: Cloud-Only Google Kubernetes Engine (GKE) Cluster** - Deploy all validation, control loops, and simulation services to a regional GKE cluster with direct MQTT connection from edge sensors.
* **Option 3: Pure Edge-Only Architecture** - Host all ingestion, rule engines, historian datastores, and dashboard interfaces exclusively on local plant on-premises hardware without cloud integration.

## Decision Outcome

Chosen option: **Option 1: Hybrid Edge (Local Deterministic Runtime) + Cloud Run (Serverless Regional Ingestion & Testing)**, because it strictly satisfies the sub-50ms fail-safe threshold and offline fallback requirements (FR-04, US5) at the physical plant perimeter while harnessing Cloud Run's automated scaling, zero-idle cost, and multi-zone resilience for cloud-tier telemetry ingestion, adversarial simulation, and API gateways.

### Adversarial Review Mitigations & Architectural Clarifications

1. **Clear Edge-to-Cloud Split & Actuation Authority (Resolving OBJ-RES-01)**:
   - **Actuator Authority**: Physical shutoff and safe-hold valve actuation are strictly and exclusively owned by the local edge fail-safe agent (`src/modules/fail_safe_gate/` running on on-premises edge hardware over direct Modbus/MQTT fieldbus loops). The cloud-side services running on Cloud Run NEVER actuate physical valves directly, completely eliminating split-brain valve control or dual-master race conditions.
   - **Cloud Role**: Cloud-side gate evaluators operate purely in an asynchronous supervisory, analytical, and audit verification role. Cloud Run evaluates historical drift, cross-plant fleet anomalies, and generates operator dashboard notifications or suggested setpoints, but cannot override local edge safety interlocks.
   - **Deterministic Sub-50ms Actuation**: Because physical trips require zero cloud round-trips or WAN dependencies, the sub-50ms hard real-time safety envelope (FR-04) is deterministically guaranteed regardless of WAN latency, jitter, or network partitions.

2. **Edge Backpressure, Memory Bounding, and Priority Tiering (Resolving OBJ-RES-02)**:
   - **Ring Buffer with Storage Caps**: Local edge fallback storage uses a bounded, fixed-capacity circular ring buffer backed by pre-allocated, write-ahead persistent storage (capped at 2 GB per edge node).
   - **Priority-Tiered Drop Policy**: When local storage reaches 80% saturation during extended WAN outages, shedding policies activate:
     - *Tier 1 (Critical Safety & Trip Events)*: Guaranteed retention, never dropped.
     - *Tier 2 (Alarm & Out-of-Envelope Records)*: Retained with second-highest priority.
     - *Tier 3 (Nominal Steady-State Telemetry)*: Shed via downsampling (e.g., retaining 1-second aggregates rather than 100ms raw samples) or dropped FIFO to preserve RAM and disk integrity.
   - This prevents edge compute crash loops, memory exhaustion, and protects local fail-safe execution.

3. **Reconnection Storm Suppression & Ingress Protection (Resolving OBJ-RES-03)**:
   - **Dynamic Traffic Shaping & Jittered Backoff**: Upon WAN reconnection, edge gateways do not dump cached telemetry in an unthrottled burst. Replay telemetry is transmitted through a secondary, throttled background queue employing truncated exponential backoff with full jitter (Decorrelated Jitter).
   - **Strict Traffic Prioritization**: Live 100ms sensor frames are prioritized over backlogged replay frames at edge network adapters and Cloud Run endpoints.
   - **Rate Limiting & Token Bucket Allocation**: Replay ingestion endpoints enforce token-bucket rate limits, and Cloud Run concurrency settings (`concurrency: 80`, min-instances configured for baseline load) ensure live telemetry stays comfortably within its 150ms processing budget without cold-start queuing.

4. **Compute Cost Optimization & Sizing (Resolving OBJ-COST-03)**:
   - **Edge Micro-Batching (1-second bundles)**: Edge agents aggregate high-frequency 100ms frames into 1-second multi-frame micro-batches (containing 10 sequential sensor readings with ordering metadata). This reduces HTTP ingress requests by 90% (from 100,000 req/sec to 10,000 req/sec across 10,000 streams).
   - **Reserved Concurrency & Predictable Compute**: Cloud Run instance auto-scaling is tuned with appropriate min-instances to handle the baseline 10,000 req/sec efficiently without thrashing. High concurrency per container instance (up to 80 concurrent connections per container) minimizes container fleet size to ~125 active instances, achieving predictable, cost-effective serverless economics while retaining scale-to-zero for ephemeral PR adversarial CI/CD simulation jobs (US3).
   - Cloud Run eliminates dedicated GKE cluster management overhead, node pool OS patching, and control plane fees.

5. **Reconciliation & Synchronization Model (Resolving OBJ-SIM-03)**:
   - **Single Source of Truth**: Replay packets contain edge-generated timestamps and sequential monotonic frame numbers. Cloud Run ingestion pipelines tag replayed batches with an `is_replayed: true` flag and route them directly to BigQuery historian tables via the BigQuery Storage Write API, bypassing real-time operational state and alerting queues.
   - This cleanly separates the live operational path from historical backfilling, eliminating dual-write reconciliation complexity and preventing false positive alarms from historical data.

### Positive Consequences

* Local edge agent executes sub-50ms emergency hardware shutoffs directly over industrial fieldbuses (Modbus/MQTT) independent of internet or cloud latency, with sole actuation authority.
* Cloud Run automatically scales compute resources up to accommodate bursty telemetry loads from 10,000 sensor streams and down to zero for on-demand adversarial PR test suites.
* Offline mode seamlessly caches telemetry locally with strict memory bounding and priority-tiered retention, preventing crash loops during extended outages.
* Micro-batched ingestion and jittered replay prevent reconnection storms and optimize Cloud Run compute costs.
* Minimizes operational overhead compared to managing dedicated Kubernetes control planes.

### Negative Consequences / Trade-offs

* Introduces dual-runtime configuration management between edge containers and Cloud Run services.
* Requires schema synchronization mechanisms between edge validation logic and cloud-based models.
* Replay pipelines require edge-side rate-shaping and server-side deduplication against BigQuery.

## Pros and Cons of the Options

### Option 1: Hybrid Edge (Local Deterministic Runtime) + Cloud Run (Serverless Regional Ingestion & Testing)

* Good, because local edge actuation reliably meets the hard sub-50ms safety deadline without internet latency jitter, with zero cloud actuation race conditions.
* Good, because Cloud Run eliminates idle compute costs during off-peak and developer testing periods while micro-batching tames continuous ingress costs.
* Good, because bounded offline fallback fulfills US5 and prevents single-point-of-failure cloud dependency.
* Bad, because edge deployments require localized device lifecycle management, priority-tiered buffer management, and over-the-air updates.

### Option 2: Cloud-Only Google Kubernetes Engine (GKE) Cluster

* Good, because centralized container orchestration unifies all workloads into a single control plane.
* Good, because high pod density supports complex multi-tenant processing.
* Bad, because WAN latency and internet outages violate the sub-50ms fail-safe requirement (FR-04) and cause severe safety hazards during plant network disconnects.
* Bad, because maintaining GKE master nodes incurs continuous baseline operational cost and infrastructure management overhead.

### Option 3: Pure Edge-Only Architecture

* Good, because all data and execution remain completely air-gapped within the industrial facility.
* Bad, because lack of centralized cloud resources prevents automated PR adversarial simulation pipelines (US3).
* Bad, because on-premises hardware limits elastic scaling for 10,000 sensor streams and inflates local maintenance and disaster recovery expenses.

## Links & References

* Official GCP Documentation: https://cloud.google.com/run/docs
* Google Cloud Architecture Framework - System Design: https://cloud.google.com/architecture/framework/system-design
* Related ADRs: ADR-0002, ADR-0003, ADR-0004
