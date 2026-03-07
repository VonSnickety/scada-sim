# AESCSF Mapping — SCADA Simulation

## Overview

The Australian Energy Sector Cyber Security Framework (AESCSF) is the cyber
security framework mandated for Australian energy and water sector organisations
operating critical infrastructure. It is based on the NIST Cybersecurity
Framework (CSF) and adapted for Australian critical infrastructure obligations
under the Security of Critical Infrastructure Act 2018 (SOCI Act).

Australian water and energy utilities use AESCSF to assess and report their
cyber security posture to regulators. The framework is organised into five functions
that together describe a complete security lifecycle.

This document maps scada-sim controls to AESCSF functions and categories,
demonstrating how a SCADA system can be designed with the framework in mind
from the start rather than mapped retrospectively.

---

## The Five Functions

```
  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
  │   IDENTIFY  │   │   PROTECT   │   │   DETECT    │   │   RESPOND   │   │   RECOVER   │
  │             │   │             │   │             │   │             │   │             │
  │ Know what   │   │ Prevent     │   │ Know when   │   │ Contain and │   │ Restore     │
  │ you have    │   │ attacks     │   │ it goes     │   │ eradicate   │   │ normal      │
  │ and what    │   │ from        │   │ wrong       │   │ incidents   │   │ operations  │
  │ matters     │   │ succeeding  │   │             │   │             │   │             │
  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
```

---

## IDENTIFY

> Develop organisational understanding of systems, assets, data, and
> capabilities to manage cyber security risk.

### Asset Management (ID.AM)

The AESCSF requires organisations to maintain an inventory of all OT and IT
assets, their interconnections, and their criticality to operations.

**Implemented in scada-sim:**

The system architecture is fully documented in `docs/threat-model.md` including:
- All components (WAF, frontend, backend, InfluxDB, Factory.io/Modbus)
- Trust zones and network boundaries
- Data flows between components
- External dependencies (Docker images, Python packages, npm packages)

**Asset inventory:**

| Asset | Type | Criticality | Owner |
|-------|------|-------------|-------|
| Factory.io Modbus endpoint | OT — sensor/actuator interface | Critical | Plant simulation |
| FastAPI backend | IT/OT boundary | Critical | Application |
| InfluxDB historian | IT — data store | High | Application |
| React HMI | IT — operator interface | High | Application |
| OWASP WAF | IT — security control | High | Infrastructure |

### Risk Assessment (ID.RA)

Threats and vulnerabilities are assessed and documented in `docs/threat-model.md`
using the STRIDE methodology. Each threat is rated by severity and has a
documented control or accepted risk with rationale.

Key risks identified:
- **T-01 (HIGH):** Modbus has no integrity checking — inherent protocol limitation
- **T-02 (MEDIUM):** No connection-level rate limiting at WAF
- **T-03 (MEDIUM):** Single-factor API key authentication

### Governance (ID.GV)

The CI/CD pipeline enforces security policy automatically on every code change:
- Gitleaks: secret management policy
- Semgrep: secure coding standards (OWASP, ICS-specific rules)
- Trivy: vulnerability management policy
- ZAP: application security testing policy

This implements a Secure Software Development Lifecycle (SSDLC) where security
gates are part of the development process, not a separate audit.

---

## PROTECT

> Develop and implement safeguards to ensure delivery of critical services.

### Identity Management and Access Control (PR.AC)

**Implemented:**

- API key authentication on all control (write) endpoints using
  `secrets.compare_digest` — prevents timing attacks during key comparison
- Read endpoints are public — consistent with real SCADA design where
  operators must always have visibility (see Accepted Risk I-01 in threat model)
- Backend container runs as non-root user (UID 1000) — limits blast radius
  of a container compromise
- Docker network isolation — each service is only reachable by intended peers;
  InfluxDB is not exposed externally

**Gap:** No individual operator identity — shared API key only. Production
would require named accounts with RBAC and individual audit trails.

### Awareness and Training (PR.AT)

The security documentation in this repository (threat model, Essential Eight
mapping, this document) serves as training material demonstrating security
awareness across:
- ICS/SCADA-specific threats (Modbus protocol limitations)
- Australian regulatory frameworks (Essential Eight, AESCSF)
- OWASP API Security Top 10

### Data Security (PR.DS)

**Implemented:**

- InfluxDB data persists in a named Docker volume — survives container restarts
- Admin token stored as environment variable, not in source code
- `.gitignore` excludes all `.env` files — secrets never committed to git
- Gitleaks scans every commit to catch accidental secret exposure
- InfluxDB not exposed externally (no external port mapping in production config)

**Gap:** No encryption at rest for historian data. No automated backup or
tested recovery procedure.

### Information Protection Processes and Procedures (PR.IP)

**Implemented:**

- Security headers on all API responses (CSP, HSTS, X-Frame-Options, etc.)
- WAF blocks OWASP Top 10 at the perimeter before requests reach application code
- Input validation via Pydantic schemas on all endpoints — rejects malformed
  or unexpected payloads
- Valve write values are bounded (0 or 32767 only) — prevents out-of-range
  commands reaching actuators
- CORS policy restricts which origins can make cross-origin requests to the API

### Protective Technology (PR.PT)

**Implemented:**

- **OWASP ModSecurity CRS** — WAF blocks SQLi, XSS, path traversal, command
  injection at the network perimeter
- **iptables rule** restricts Modbus port 502 to Docker bridge subnet only —
  network-level OT boundary enforcement
- **Docker network segmentation** — services communicate only on internal
  networks; only the WAF is exposed externally
- **Rate limiting** (slowapi) — 60 requests/minute on state endpoint prevents
  automated scraping and basic DoS

---

## DETECT

> Develop and implement activities to identify the occurrence of a
> cyber security event.

### Anomalies and Events (DE.AE)

**Implemented:**

The alarm subsystem in `backend/app/factoryio_client.py` implements process
anomaly detection — continuously comparing sensor values against defined
process limits:

| Alarm ID | Condition | Severity | Significance |
|----------|-----------|----------|--------------|
| T001_HH | Tank level ≥ 90% | CRITICAL | Overflow imminent |
| T001_HIGH | Tank level ≥ 80% | HIGH | Operator intervention required |
| T001_LOW | Tank level ≤ 20% | WARN | Low supply warning |
| T001_LL | Tank level ≤ 10% | CRITICAL | Pump cavitation risk |
| SYS_COMMS_LOST | Modbus connection lost | CRITICAL | Cannot monitor/control plant |

These are process alarms (detecting abnormal plant behaviour) rather than
cyber security alarms. In production, cyber-specific detection would include:
- Failed authentication attempts (rate limiting currently provides partial signal)
- Unexpected Modbus write patterns (anomaly detection on actuator commands)
- Network traffic outside expected baselines

### Security Continuous Monitoring (DE.CM)

**Implemented:**

- **InfluxDB historian** records all sensor values every 5 seconds — provides
  a continuous audit trail of plant state
- **Backend logging** records all control commands with timestamp and source IP
- **GitHub Actions** runs security scans on every push — continuous monitoring
  of the codebase for new vulnerabilities

**Gap:** No real-time security event monitoring (SIEM). Logs are not aggregated
or alerted on. In production, a SIEM (Splunk, Elastic) would ingest WAF logs,
application logs, and Modbus traffic for correlation and alerting.

### Detection Processes (DE.DP)

**Implemented:**

- OWASP ZAP DAST runs on every push to trunk — automated detection testing
  to verify that security controls are working correctly
- ZAP report is uploaded as a build artifact — evidence of detection capability
  for each release

---

## RESPOND

> Develop and implement activities to take action regarding a detected
> cyber security incident.

### Response Planning (RS.RP)

**Implemented at lab scope:**

The CI/CD pipeline provides automated response to detected vulnerabilities:

1. **Trivy** finds a HIGH/CRITICAL CVE → build fails → deployment blocked
2. **Gitleaks** finds a committed secret → build fails → push rejected
3. **Semgrep** finds an insecure code pattern → build fails → PR cannot merge
4. **ZAP** finds a new vulnerability → warning logged → report artifact generated

This is automated response at the code/build level. Process-level incident
response (who to call, how to isolate, how to preserve evidence) is out of
scope for a simulation project but documented as a production gap.

### Communications (RS.CO)

**Implemented:**

- GitHub Actions sends email notifications on workflow failures to the
  repository owner — automated alerting on security scan failures
- All failed authentication attempts return consistent error responses
  without leaking information about key validity

### Analysis (RS.AN)

**Implemented:**

- **InfluxDB historian** provides 60-minute trend data via `/api/history/:field`
  — operators can review plant state leading up to an incident
- **Modbus comms loss alarm** (SYS_COMMS_LOST) immediately surfaces loss of
  OT visibility — operators know immediately if monitoring is compromised
- All control commands are logged with source IP and value — supports
  post-incident timeline reconstruction

### Mitigation (RS.MI)

**Implemented:**

- Valve control endpoints require authentication — an attacker who bypasses
  read access cannot automatically gain control access
- iptables rule limits Modbus exposure — network-level containment if
  application layer is compromised
- `MOCK_MODE` allows the system to be run in a safe state for testing and
  incident investigation without affecting the real plant

---

## RECOVER

> Develop and implement activities to maintain resilience and restore
> capabilities after a cyber security incident.

### Recovery Planning (RC.RP)

**Implemented at lab scope:**

- Docker Compose stack can be fully rebuilt from source in under 5 minutes —
  `docker compose up --build` recreates all containers from scratch
- InfluxDB data persists in a named volume — historian survives container
  rebuilds
- All configuration is in version control — known-good state is always
  recoverable from git

**Gaps for production:**

- No tested recovery runbook (step-by-step procedure)
- No Recovery Time Objective (RTO) or Recovery Point Objective (RPO) defined
- No off-site backup of historian data
- Single-instance deployment — no failover

### Improvements (RC.IM)

The post-incident improvement loop is implemented via the CI/CD pipeline:

1. Vulnerability found (by scan, ZAP, or incident)
2. Fix developed on a feature branch
3. Security scans re-run — fix verified before merge
4. New controls documented in threat model and this mapping
5. Commit history provides audit trail of security improvements

This demonstrates a continuous improvement posture rather than point-in-time
compliance.

---

## Summary Table

| AESCSF Function | Category | Implementation | Maturity |
|----------------|----------|----------------|----------|
| **IDENTIFY** | Asset Management | Architecture documented, asset inventory maintained | Partial |
| **IDENTIFY** | Risk Assessment | STRIDE threat model, risks rated and documented | Implemented |
| **IDENTIFY** | Governance | CI/CD security gates enforce policy on every push | Implemented |
| **PROTECT** | Access Control | API key auth, non-root containers, network isolation | Partial |
| **PROTECT** | Data Security | Secrets in env vars, gitignored, Gitleaks scanning | Implemented |
| **PROTECT** | Protective Technology | WAF (OWASP CRS), iptables OT boundary, rate limiting | Implemented |
| **PROTECT** | Info Protection | Security headers, input validation, CORS | Implemented |
| **DETECT** | Anomaly Detection | Process alarms (HH/H/L/LL), comms loss detection | Implemented |
| **DETECT** | Continuous Monitoring | Historian, command logging, CI security scans | Partial |
| **RESPOND** | Response Planning | Automated build-gate response to CVEs/findings | Partial |
| **RESPOND** | Analysis | Historian trend data, command audit log | Partial |
| **RESPOND** | Mitigation | Auth separation, network containment, mock mode | Implemented |
| **RECOVER** | Recovery Planning | Full stack rebuildable from source, volume persistence | Partial |
| **RECOVER** | Improvements | CI/CD loop implements continuous improvement | Implemented |

**Primary gaps vs. production AESCSF compliance:**
- Individual operator identity and RBAC (shared API key is insufficient)
- SIEM/log aggregation for security event correlation
- Formal backup and tested recovery procedure
- MFA for operator access
- Encrypted communications (TLS) throughout

---

## References

- [AESCSF Framework](https://www.energycouncil.com.au/initiatives/aescsf/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
- [Security of Critical Infrastructure Act 2018](https://www.legislation.gov.au/Details/C2018A00029)
- [ACSC Essential Eight](https://www.cyber.gov.au/resources-business-and-government/essential-cyber-security/essential-eight)
- [IEC 62443](https://www.iec.ch/homepage) — Industrial Automation and Control Systems Security
