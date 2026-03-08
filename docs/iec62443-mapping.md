# IEC 62443 Security Requirements Mapping — SCADA Simulation

## Overview

IEC 62443 is the international standard for Industrial Automation and Control System
(IACS) security. Where OWASP addresses web application vulnerabilities and the
Essential Eight addresses general IT posture, IEC 62443 is purpose-built for
operational technology environments — PLCs, SCADA systems, field devices, and the
networks that connect them.

The standard organises requirements into seven **Foundational Requirements (FRs)**,
each containing specific **Security Requirements (SRs)**. Requirements are rated
against four **Security Levels (SLs)**:

- **SL 1** — Protection against unintentional or coincidental violation
- **SL 2** — Protection against intentional violation using simple means (opportunistic attacker)
- **SL 3** — Protection against sophisticated means with moderate resources (motivated attacker)
- **SL 4** — Protection against state-sponsored or highly resourced attackers

This document maps the controls implemented in scada-sim to the most relevant SRs.
Gaps are documented honestly with notes on what production implementation would require.

---

## FR 1 — Identification and Authentication Control (IAC)

> Ensure all users, software processes, and devices are identified and authenticated
> before being granted access to the IACS.

### SR 1.1 — Human User Identification and Authentication

**What we implemented:**

- All actuator control endpoints (`POST /api/control/*`, `POST /api/alarms/*/acknowledge`)
  require an `X-API-Key` header validated against `settings.api_key`
- Comparison uses `secrets.compare_digest()` — constant-time comparison that prevents
  timing-based key enumeration attacks
- Read endpoints (`GET /api/state`, `GET /api/alarms`) are intentionally public —
  operators need live data without friction; documented as accepted risk I-01 in
  threat model
- The audit log endpoint (`GET /api/audit`) is protected — control history is sensitive

**Evidence:**

- `backend/app/auth.py` — `verify_api_key()` with constant-time comparison
- `backend/app/api/routes.py` — `Depends(verify_api_key)` on all control endpoints
- `.semgrep/ics-security.yml` Rule 7 — CI blocks any new POST endpoint missing auth

**Gaps:**

- Shared API key provides no individual identity — all key holders are
  indistinguishable in the audit log. Production SCADA would use named operator
  accounts with individual credentials and RBAC

**Security Level: SL 1–2**

Authentication is present and timing-attack safe. Insufficient for SL 3 without
individual identity and multi-factor authentication.

---

### SR 1.3 — Account Management

**What we implemented:**

- No formal account management — single shared API key
- Key rotation is possible via `API_KEY` environment variable without code changes
- Key is never hardcoded in source (Semgrep Rule 5 enforces this in CI)

**Gaps:**

- No account creation, suspension, or expiry process
- No individual named accounts
- No privileged account review cycle

**Security Level: SL 1**

Minimal — acceptable for lab scope. Production would require identity management
(Active Directory, LDAP, or purpose-built SCADA IAM).

---

## FR 2 — Use Control (UC)

> Ensure that all users, software processes, and devices have only the access
> necessary to perform their authorised function (least privilege).

### SR 2.1 — Authorisation Enforcement

**What we implemented:**

- Two-tier access model: public read vs. authenticated control
- Control endpoints enforce `Depends(verify_api_key)` at the route level
- Pydantic models on all control endpoints — malformed payloads rejected before
  business logic runs (OWASP A03 Injection)
- Backend container runs as non-root (`appuser`, UID 1000) — process cannot write
  to host filesystem even if compromised

**Evidence:**

- `backend/app/api/routes.py` — tiered access model
- `backend/Dockerfile` — non-root user setup
- `.semgrep/ics-security.yml` Rule 7 — automated enforcement of auth on POST endpoints

**Security Level: SL 2**

---

### SR 2.8 — Auditable Events

**What we implemented:**

- Every actuator command (fill valve open/close, discharge valve open/close) is
  recorded in the audit log with: UTC timestamp, action, actor IP, outcome
  (success/failure), and error detail on failure
- Every alarm acknowledgement is recorded with the same fields
- Audit log is accessible via `GET /api/audit` (API key required)
- In-memory circular buffer bounded at 1000 entries — oldest entries dropped
  automatically; no audit data lost during normal operation
- Semgrep Rule 6 enforces audit logging on all future POST endpoints in CI —
  a developer cannot add a control endpoint without `_audit.record()` or CI blocks

**Evidence:**

- `backend/app/audit.py` — AuditLog implementation
- `backend/app/api/routes.py` — audit.record() calls in all control endpoints
- `.semgrep/ics-security.yml` Rule 6 — CI enforcement

**Gaps:**

- In-memory only — audit log does not survive a container restart. Production
  would persist to InfluxDB, a syslog target, or a SIEM
- Actor is IP address only — no individual identity (see SR 1.1)

**Security Level: SL 2**

Comprehensive event capture with CI-enforced coverage. Persistence and individual
identity attribution needed for SL 3.

---

## FR 3 — System Integrity (SI)

> Ensure the integrity of the IACS against compromise by malicious content or
> unauthorised change.

### SR 3.4 — Software and Information Integrity

**What we implemented:**

- **Gitleaks** scans full git history on every push — detects secrets accidentally
  committed at any point, not just the current state
- **GPG/SSH commit signing** — every commit is cryptographically signed, providing
  tamper evidence for the source history
- **Trivy** verifies OS and Python dependency integrity against the CVE database —
  detects tampered or vulnerable packages introduced into the supply chain
- **Semgrep** SAST runs on every push — detects code changes that introduce
  known-bad patterns

**Evidence:**

- `.github/workflows/security.yml` — Gitleaks, Semgrep, Trivy jobs
- Git commit signing configuration — all trunk commits show as Verified on GitHub

**Security Level: SL 2**

---

### SR 3.5 — Input Validation

**What we implemented:**

- All API request bodies are validated by **Pydantic models** — FastAPI returns 422
  before our code runs if the payload doesn't match the schema
- History endpoint validates `field` against an explicit allowlist
  (`{"tank_level", "flow_rate", "setpoint", "alarm_count"}`) — rejects arbitrary
  field names that could be used for injection
- `minutes` parameter on history endpoint is bounds-checked (1–1440) — prevents
  denial of service via unbounded time range queries
- Alarm acknowledgement validates alarm ID against active alarms — returns 404 if
  not found rather than silently succeeding

**Evidence:**

- `backend/app/api/routes.py` — Pydantic models, allowlist checks, bounds validation
- `.semgrep/ics-security.yml` Rule 3 — flags unbounded Modbus register writes

**Security Level: SL 2**

---

### SR 3.6 — Deterministic Output

> Ensure that outputs from the IACS remain within defined safe operating ranges.

**What we implemented:**

- Fill and discharge valve commands accept boolean only (`open: true/false`) — no
  partial positions or arbitrary values accepted at the API layer
- Modbus register writes use fixed safe values: `32767` (fully open) or `0`
  (fully closed) — no user-supplied numeric value reaches the register write
- Semgrep Rule 3 (`modbus-write-unbounded-value`) flags any future code that
  passes an unclamped value to a register write — CI enforces this

**Evidence:**

- `backend/app/factoryio_client.py` — `cmd_fill_valve()`, `cmd_discharge_valve()`
- `.semgrep/ics-security.yml` Rule 3

**Security Level: SL 2**

---

## FR 6 — Timely Response to Events (TRE)

> Respond to security violations by notifying the proper authority, reporting
> the necessary evidence, and taking timely corrective action.

### SR 6.1 — Audit Log Accessibility

**What we implemented:**

- `GET /api/audit` returns the 100 most recent entries by default, up to 500
- Results are newest-first — most recent events immediately visible
- Endpoint is API key protected — audit data is not publicly accessible
- `limit` parameter is server-side clamped (1–500) — client cannot request an
  unbounded dump

**Evidence:**

- `backend/app/api/routes.py` — `get_audit_log()` endpoint
- `backend/app/audit.py` — `recent()` method

**Security Level: SL 2**

---

### SR 6.2 — Continuous Monitoring

**What we implemented:**

- **Polling loop** reads all plant sensors every second — tank level, flow rate,
  setpoint, valve states, running status
- **Process alarms** fire automatically when values cross thresholds:
  - T001_HH: tank ≥ 90% (overflow risk)
  - T001_HIGH: tank ≥ 80%
  - T001_LL: tank ≤ 10% (pump cavitation risk)
  - T001_LOW: tank ≤ 20%
  - FLOW_NO_FLOW: fill valve open + zero flow for 3 consecutive polls (blocked pipe
    or sensor fault)
- **Alarm acknowledgement** provides operator confirmation loop — acknowledged
  alarms remain visible but are visually distinguished
- **Modbus reconnection** — if the connection to Factory.io drops, the system
  attempts reconnect on the next poll and raises `SYS_COMMS_LOST` alarm
- **OWASP ZAP** performs continuous dynamic testing on every push — automated
  regression testing for exploitable vulnerabilities

**Evidence:**

- `backend/app/factoryio_client.py` — `_evaluate_alarms()`, reconnect logic
- `backend/app/historian.py` — polling loop
- `.github/workflows/dast.yml` — ZAP continuous monitoring

**Security Level: SL 2**

---

## FR 7 — Resource Availability (RA)

> Ensure the availability of the IACS against degradation or denial of service.

### SR 7.1 — Denial of Service Protection

**What we implemented:**

- **slowapi rate limiting** on all API endpoints — `GET /api/state` limited to
  60 requests/minute per IP
- **CORS policy** restricts cross-origin requests to known frontend origins only —
  prevents cross-site request abuse
- In-memory audit log uses a bounded `deque(maxlen=1000)` — cannot be exhausted
  by flooding the control endpoints

**Evidence:**

- `backend/app/api/routes.py` — `@limiter.limit("60/minute")`
- `backend/app/main.py` — CORS configuration
- `backend/app/audit.py` — bounded deque

**Security Level: SL 1–2**

Rate limiting in place. No protection against volumetric network-layer DoS —
would require upstream load balancer or WAF in production.

---

### SR 7.6 — Network and Security Configuration Settings

**What we implemented:**

- Modbus host and port are read from `settings.factoryio_host` and
  `settings.factoryio_port` — never hardcoded in source
- Semgrep Rule 1 (`hardcoded-modbus-host`) fails CI if a Modbus client is
  instantiated with a string literal instead of a config value
- All security-relevant configuration (API key, InfluxDB token, OPC-UA endpoint)
  is loaded from environment variables via pydantic-settings — `.env` file
  is gitignored and never committed

**Evidence:**

- `backend/app/config.py` — Settings class, env var loading
- `.semgrep/ics-security.yml` Rule 1

**Security Level: SL 2**

---

### SR 7.7 — Least Functionality

> Restrict the IACS to only the functions, ports, protocols, and services required.

**What we implemented:**

- **Mock mode** (`MOCK_MODE=true`) bypasses the real Modbus connection — exists
  for CI/testing only and must never be deployed to production
- Semgrep Rule 4 (`mock-mode-hardcoded-true`) fails CI if `mock_mode = True` is
  hardcoded — prevents accidental deployment of mock mode to production
- CORS limits allowed HTTP methods to `GET`, `POST`, `OPTIONS` only
- nginx serves only static files and proxies only `/api/` — no directory listing,
  no server version exposure

**Evidence:**

- `.semgrep/ics-security.yml` Rule 4
- `backend/app/main.py` — CORS allowed methods
- `frontend/nginx.conf` — restricted proxy configuration

**Security Level: SL 2**

---

## Summary

| Foundational Requirement | SR | Security Level | Primary Gap |
|---|---|---|---|
| FR 1 — Identification & Auth | SR 1.1 Human User Auth | SL 2 | Individual identity, MFA |
| FR 1 — Identification & Auth | SR 1.3 Account Management | SL 1 | No account lifecycle |
| FR 2 — Use Control | SR 2.1 Authorisation | SL 2 | No RBAC |
| FR 2 — Use Control | SR 2.8 Auditable Events | SL 2 | No persistence across restarts |
| FR 3 — System Integrity | SR 3.4 Software Integrity | SL 2 | — |
| FR 3 — System Integrity | SR 3.5 Input Validation | SL 2 | — |
| FR 3 — System Integrity | SR 3.6 Deterministic Output | SL 2 | — |
| FR 6 — Timely Response | SR 6.1 Audit Accessibility | SL 2 | — |
| FR 6 — Timely Response | SR 6.2 Continuous Monitoring | SL 2 | — |
| FR 7 — Resource Availability | SR 7.1 DoS Protection | SL 2 | No network-layer DoS protection |
| FR 7 — Resource Availability | SR 7.6 Network Config | SL 2 | — |
| FR 7 — Resource Availability | SR 7.7 Least Functionality | SL 2 | — |

**Overall posture: SL 2 across implemented controls.**

Primary gaps for SL 3 are individual user identity (named accounts, MFA), persistent
audit log storage, and network-layer availability protection — all documented with
production remediation paths above.
