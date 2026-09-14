# Story <-> Subsystem Traceability Matrix

> **Status**: FROZEN / BASELINE (Gate 0.5)  
> **Source**: Lead Cloud Architect (`/architect-design`)  
> **Traceability Standard**: Every PRD User Story must map to at least one realizing subsystem, and every subsystem must serve at least one story.

| User Story ID | Subsystem(s) Realizing Story | Realization Description & Boundary Scope |
|---|---|---|
| **US-1** | `src/modules/flow_ingestion`, `src/modules/fail_safe_gate` | Telemetry packet ingestion over MQTT/Modbus via `flow_ingestion` with schema and signature checks, followed by static envelope and dynamic correlation validation in `fail_safe_gate`. |
| **US-2** | `src/modules/fail_safe_gate` | Real-time sensor freeze detection, missing heartbeat monitoring, and sub-50ms hardware interrupt "Close-Gate" dispatching. |
| **US-3** | `src/modules/fail_safe_gate` | Automated adversarial test suite runner injecting synthetic flow spikes, vacuum drops, and sensor turbulence into regulator logic during CI/CD PR cycles. |
| **US-4** | `src/modules/observability_dashboard` | Real-time flow health dashboard, gate trip incident logs, automated root-cause summaries, and sub-60s notification routing to on-call engineers. |
| **US-5** | `src/modules/fail_safe_gate`, `src/modules/flow_ingestion` | Offline fallback mode executing locally cached safety policies, circular buffer queuing during WAN disconnects, and prioritized historian replay upon network reconnection. |
