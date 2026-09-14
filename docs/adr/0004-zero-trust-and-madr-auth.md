# [ADR-0004] Zero-Trust Perimeter, Cryptographic Signing, and Identity Architecture

* **Status**: accepted
* **Deciders**: Lead Cloud Architect, SecOps Architect, Tech Lead
* **Date**: 2026-09-14
* **Superseded by**: N/A
* **Approved-by**: Lead Cloud Architect

## Context and Problem Statement

Industrial gas control systems represent high-consequence critical infrastructure. Malicious alteration of flow commands or spoofed telemetry could lead to hazardous chemical runaway or equipment destruction. The PRD mandates that all telemetry data must be cryptographically signed at the edge to prevent spoofing or man-in-the-middle tampering, and that administrative access to modify safety envelopes must be restricted strictly to authorized personnel such as Dr. Elena Vance using Identity-Aware Proxy (IAP) and IAM roles (NFR Security & Compliance). The architecture requires a holistic Zero-Trust security perimeter spanning edge device authentication, edge-to-cloud transport security, perimeter DDoS defense, and secret protection.

## Decision Drivers

* **Data Integrity & Non-Repudiation (NFR Security & Compliance)**: Telemetry packets must be cryptographically signed at the plant edge and validated before entering downstream decision loops.
* **Granular Role-Based Access Control (NFR Security, US4)**: Strict separation of privileges where only authorized engineers can alter threshold policies, while plant operators receive read-only dashboard access.
* **Perimeter Defense against Layer 7 & DDoS Attacks**: Publicly reachable ingress endpoints must be protected against malicious payloads, scanning, and flooding attacks.
* **Zero Plaintext Secrets**: Application code and CI/CD pipelines must never store static API keys, TLS certificates, or HMAC tokens in source control.

## Considered Options

* **Option 1: Defense-in-Depth Zero-Trust with Cloud Armor, Identity-Aware Proxy (IAP), Cloud KMS, and Secret Manager** - Edge devices sign telemetry frames using HMAC-SHA256 with keys managed via Secret Manager; Cloud Armor defends ingress load balancers; IAP enforces contextual identity authentication for human users; Cloud KMS manages customer-managed encryption keys.
* **Option 2: VPN / Private Interconnect with Basic HTTP Authentication** - Rely on a dedicated site-to-site IPsec VPN tunnel with basic username/password or API token headers for service-to-service communication.
* **Option 3: Perimeter Firewall Rules with Shared Static API Keys** - Expose endpoints over public IP addresses protected solely by GCP Compute firewall rules and shared hardcoded API keys.

## Decision Outcome

Chosen option: **Option 1: Defense-in-Depth Zero-Trust with Cloud Armor, Identity-Aware Proxy (IAP), Cloud KMS, and Secret Manager**, because it delivers robust end-to-end cryptographic non-repudiation, granular Google-managed identity access for human operators via IAP, automated DDoS and OWASP Top 10 mitigation via Cloud Armor, and zero plaintext secret leakage via Secret Manager and Cloud KMS.

### Adversarial Review Mitigations & Architectural Clarifications

1. **In-Memory Cryptographic Key Caching & Decoupling from Secret Manager (Resolving OBJ-RES-08 & OBJ-COST-05)**:
   - **Local In-Memory Key Cache with TTL**: Cloud Run ingress instances pre-fetch and cache HMAC signing keys and certificate verification material in process memory during container startup, using a Time-To-Live (TTL) cache (e.g., 1-hour refresh interval with asynchronous background renewal).
   - **Eliminating Runtime Secret Manager Dependency**: Zero runtime Secret Manager or Cloud KMS API calls are made on the high-frequency packet ingestion path. HMAC verification executes in pure CPU memory (<0.05ms per frame) using pre-warmed keys.
   - **Outage Resilience & Zero Cost Overhead**: Transient outages or rate-limiting of Secret Manager/KMS do not affect incoming packet verification. Secret Manager API operations drop from 260 billion/month to fewer than 10,000/month (practically $0.00/month).
   - **Micro-Batched Verification**: Edge 1-second multi-frame aggregation means HMAC verification runs once per 1-second batch rather than 10 times per second, reducing ingress cryptographic CPU load by 90%.

2. **Cloud Armor Rate Limiting, Emergency Burst Profiling & IP Allowlisting (Resolving OBJ-RES-09)**:
   - **Dedicated Ingress Policy with Plant CIDR Allowlisting**: Cloud Armor policies define separate rules for machine-to-machine edge gateways versus human operator web traffic:
     - *Plant Perimeter Gateway Rule*: Traffic originating from verified, static plant egress IP CIDRs with valid mutual TLS certificates is matched against a high-threshold burst policy or bypasses volumetric throttling.
     - *Emergency Burst Headroom*: Rate limiting thresholds are provisioned for 5x normal peak (e.g., 50,000 req/sec headroom per plant gateway) to ensure legitimate safety trips, emergency state packets, and post-fault sensor bursts are never dropped or rate-limited.
     - *Layer 7 WAF Rules*: Standard OWASP Top 10 rules apply strictly to malicious web attacks without blocking structured industrial sensor binary/JSON payloads.

3. **Justification of Zero-Trust Defense-in-Depth over mTLS Alone (Resolving OBJ-SIM-04)**:
   - **Defense-in-Depth vs Single Point of Compromise**: While mTLS terminates at the External HTTPS Load Balancer, it provides transport security only up to the perimeter proxy. In safety-critical gas infrastructure handling explosive volatile chemicals, payload-level HMAC signing guarantees end-to-end non-repudiation and data integrity directly from edge field devices through to the fail-safe evaluators, protecting against internal network lateral movement, compromised reverse proxies, or misconfigured ingress routing.
   - **Role Separation**: Identity-Aware Proxy (IAP) secures human administrative access (Dr. Elena Vance modifying safety envelopes) via Google corporate identities and MFA, completely separate from machine-to-machine sensor ingestion. Cloud KMS CMEK ensures compliance with industrial data protection regulations. Each security layer addresses a distinct threat vector with zero runtime coupling to high-frequency decision loops.

### Positive Consequences

* Edge payload signatures (HMAC-SHA256) prevent man-in-the-middle injection and spoofing of critical flow adjustments.
* In-memory key caching eliminates synchronous Secret Manager runtime dependencies, isolates ingress from GCP API rate limits, and slashes API costs to zero.
* Edge micro-batching reduces cryptographic verification CPU load by 90%.
* Cloud Armor plant gateway allowlists and 5x burst headroom guarantee that emergency plant trip events are never throttled.
* Identity-Aware Proxy eliminates the need for vulnerable corporate VPNs while enforcing contextual MFA and IAM policies for safety threshold modifications.
* Secret Manager ensures sensitive plant credentials, TLS certificates, and cryptographic keys are versioned, audited, and injected dynamically into runtime memory.
* Cloud KMS ensures cryptographic control of data at rest across BigQuery, Firestore, and Cloud Storage.

### Negative Consequences / Trade-offs

* Edge device keys require an automated rotation protocol with graceful multi-key overlap during transitions.
* Cloud Run ingress instances require memory-cached key management and background TTL eviction logic.

## Pros and Cons of the Options

### Option 1: Defense-in-Depth Zero-Trust with Cloud Armor, Identity-Aware Proxy (IAP), Cloud KMS, and Secret Manager

* Good, because it adheres strictly to Google Cloud Well-Architected Framework Zero-Trust security guidelines.
* Good, because in-memory key caching eliminates synchronous runtime external API failure modes.
* Good, because plant allowlists and burst headroom protect safety-critical alarm telemetry.
* Good, because IAP provides seamless browser-based authentication with IAM least privilege for the Operations Dashboard.
* Good, because Cloud Armor stops volumetric DDoS attacks and malicious web traffic before reaching compute services.
* Bad, because edge device key provisioning requires initial secure bootstrapping and key cache warming procedures.

### Option 2: VPN / Private Interconnect with Basic HTTP Authentication

* Good, because all network traffic remains encapsulated within an encrypted tunnel.
* Bad, because VPN concentrators become single points of failure and throughput bottlenecks for 10,000 sensor streams.
* Bad, because basic authentication lacks contextual multi-factor verification, auditability, and automated credential rotation.

### Option 3: Perimeter Firewall Rules with Shared Static API Keys

* Good, because simple configuration requires minimal initial setup effort.
* Bad, because static API keys in edge firmware represent a critical credential exfiltration vulnerability.
* Bad, because simple IP firewalling cannot protect against application-layer injection or credential compromise.

## Links & References

* Official GCP Documentation: https://cloud.google.com/armor/docs
* Official GCP Documentation: https://cloud.google.com/iap/docs
* Official GCP Documentation: https://cloud.google.com/secret-manager/docs
* Official GCP Documentation: https://cloud.google.com/kms/docs
* Google Cloud Architecture Framework - Security: https://cloud.google.com/architecture/framework/security
* Related ADRs: ADR-0001, ADR-0002, ADR-0003
