# ASD Essential Eight Mapping — SCADA Simulation

## Overview

The Australian Signals Directorate (ASD) Essential Eight is the baseline
cyber security framework for Australian government and critical infrastructure
organisations. Organisations operating critical infrastructure under the
Security of Critical Infrastructure Act 2018 (SOCI Act) are required to
demonstrate alignment.

This document maps the controls implemented in scada-sim to each of the eight
mitigation strategies, with an honest maturity level assessment.

**Maturity Levels:**
- **ML0** — Not implemented
- **ML1** — Partly implemented, ad hoc
- **ML2** — Implemented, documented, tested
- **ML3** — Implemented, optimised, continuously monitored

---

## 1. Patch Applications

> Keep applications patched against known vulnerabilities.

### What we implemented

- **Dependabot** auto-raises PRs within 24 hours of a CVE patch being released
  for Python packages, npm packages, Docker base images, and GitHub Actions
- **Trivy** scans the backend Docker image on every push and fails the build
  if HIGH or CRITICAL CVEs are found with available fixes
- **requirements.txt** uses minimum version bounds (`>=`) so pip always resolves
  to the latest patched version rather than a pinned vulnerable one
- **CVE-2024-47874** (starlette DoS) and **CVE-2025-62727** (starlette Range
  header DoS) were identified by Trivy and remediated within the same CI run

### Evidence

- `.github/workflows/security.yml` — Trivy job
- `.github/dependabot.yml` — automated dependency monitoring
- `backend/requirements.txt` — minimum version pinning strategy

### Maturity Level: ML2

Automated scanning and alerting in place. Manual review still required to
merge Dependabot PRs and validate breaking changes before deployment.

---

## 2. Patch Operating Systems

> Keep operating systems patched against known vulnerabilities.

### What we implemented

- Docker base images use **distroless/slim variants** (`python:3.x-slim`,
  `nginx:alpine`) which minimise the OS attack surface — fewer packages means
  fewer CVEs
- **Dependabot** monitors Docker base image versions and raises PRs when new
  images are available (e.g. `python:3.12-slim → 3.14-slim`)
- **Trivy** scans OS-level packages in the container image as part of the same
  CI scan (not just Python libraries — also checks libc, openssl, etc.)
- The host OS (CachyOS Linux) uses a rolling release model with the BORE
  kernel — security patches are available within hours of upstream release

### Maturity Level: ML1

Automated monitoring in place for container OS packages. No formal patch
schedule or SLA for applying Dependabot Docker PRs — would need to be defined
for production.

---

## 3. Multi-Factor Authentication

> Use MFA for remote access and privileged accounts.

### What we implemented

- **Not implemented** — the API uses a single shared API key with no second factor
- The GitHub repository itself is protected by GitHub account MFA (personal
  security posture, not in-scope for the application)

### Rationale for ML0

This is a simulation/lab environment with no real operators or privileged
accounts. In production water treatment SCADA:

- Operator workstations would require MFA (smartcard + PIN, or TOTP)
- Remote access to the OT network would require MFA VPN (e.g. Cisco Duo)
- The SCADA application would use individual named accounts with RBAC,
  not a shared API key
- Privileged actions (valve commands) would require a second confirmation
  step (two-operator rule for critical operations)

### Maturity Level: ML0

Accepted gap for lab scope. Documented as T-03 in threat model.

---

## 4. Restrict Administrative Privileges

> Limit admin privileges to only those who need them.

### What we implemented

- Backend container runs as **non-root user** (`appuser`, UID 1000) — the
  Dockerfile explicitly creates and switches to this user
- **API key auth** separates read access (public) from control access
  (key required) — operators cannot command actuators without the key
- **Pydantic input validation** on all control endpoints — malformed payloads
  are rejected before reaching any business logic
- InfluxDB admin token is only used at container init, not at runtime — the
  backend uses a write-scoped token

### Evidence

- `backend/Dockerfile` — non-root user setup
- `backend/app/auth.py` — API key verification
- `backend/app/api/routes.py` — `Depends(verify_api_key)` on control endpoints

### Maturity Level: ML2

Privilege separation implemented at application and container level. No RBAC
for individual operators — all key holders have equal control access.

---

## 5. Application Control (Allowlisting)

> Only allow approved applications to execute.

### What we implemented

- **OWASP ModSecurity WAF** with Core Rule Set (CRS) acts as an application-
  layer allowlist — only requests matching expected patterns are forwarded;
  SQLi, XSS, path traversal, command injection are blocked before reaching
  the app
- **ALLOWED_METHODS=GET POST HEAD OPTIONS** — the WAF rejects all other HTTP
  methods (PUT, DELETE, PATCH, TRACE etc.) at the perimeter
- **Pydantic schemas** enforce strict input types on all API endpoints —
  unexpected fields are rejected (OWASP A03 Injection)
- **Docker containers** isolate each service — a compromise of one container
  cannot directly execute on the host or other containers

### Evidence

- `docker-compose.yml` — WAF configuration, ALLOWED_METHODS
- `backend/app/api/routes.py` — Pydantic models for all request bodies

### Maturity Level: ML1

Request-level allowlisting via WAF and input validation. No host-level
application control (e.g. AppArmor, seccomp profiles on containers) — would
be required for ML2 in production.

---

## 6. Restrict Microsoft Office Macros

> Disable or restrict Office macros.

### Not applicable

This control targets Windows desktop environments where phishing via macro-
enabled Office documents is a common initial access vector. scada-sim runs
on Linux with no Office suite in scope.

In a real water utility context this would apply to the corporate IT network
(operator desktops, engineering workstations) but is out of scope for the
OT/SCADA layer documented here.

### Maturity Level: N/A

---

## 7. User Application Hardening

> Harden browsers and other user-facing applications.

### What we implemented

- **Security headers** on every API response prevent common browser-based
  attacks against the HMI:

  | Header | Attack prevented |
  |--------|-----------------|
  | `X-Content-Type-Options: nosniff` | MIME type sniffing |
  | `X-Frame-Options: DENY` | Clickjacking via iframe |
  | `X-XSS-Protection: 1; mode=block` | Reflected XSS (legacy browsers) |
  | `Content-Security-Policy: default-src 'self'` | XSS, data injection |
  | `Strict-Transport-Security` | SSL stripping, protocol downgrade |
  | `Referrer-Policy: strict-origin-when-cross-origin` | Referrer leakage |
  | `Cross-Origin-Resource-Policy: same-origin` | Cross-origin data leaks |

- **nginx security headers** on the frontend (X-Content-Type-Options,
  X-Frame-Options, X-XSS-Protection)
- **OWASP ZAP DAST** validates that headers are present and correct on every
  push — automated regression testing for header configuration

### Evidence

- `backend/app/main.py` — SecurityHeadersMiddleware
- `frontend/nginx.conf` — security headers
- `.github/workflows/dast.yml` — automated header validation

### Maturity Level: ML2

Headers implemented and automatically validated. CSP could be tightened
further (nonces for inline scripts) for ML3.

---

## 8. Regular Backups

> Back up important data and test restoration.

### What we implemented

- **InfluxDB data** is stored in a named Docker volume (`influxdb_data`) which
  persists across container restarts
- The volume is on the host filesystem and can be backed up with standard
  tools (`docker run --volumes-from` or `influx backup`)

### Gaps

- No automated backup schedule implemented
- No backup restoration test procedure documented
- No off-site or encrypted backup

### Maturity Level: ML0

Data persistence implemented (survives restarts) but no formal backup/recovery
process. For a production historian this would be critical — losing sensor
history makes incident investigation impossible.

---

## Summary

| Strategy | Maturity | Notes |
|----------|----------|-------|
| 1. Patch Applications | ML2 | Dependabot + Trivy automated |
| 2. Patch OS | ML1 | Container images monitored, no formal schedule |
| 3. MFA | ML0 | Lab scope — shared API key only |
| 4. Restrict Admin Privileges | ML2 | Non-root containers, API key separation |
| 5. Application Control | ML1 | WAF + Pydantic; no host-level allowlisting |
| 6. Office Macros | N/A | Linux environment, not applicable |
| 7. User App Hardening | ML2 | Security headers, ZAP validated |
| 8. Backups | ML0 | Volume persistence only, no backup process |

**Overall posture:** ML1–ML2 across applicable controls. Primary gaps are MFA
(accepted for lab), backup process, and host-level application control — all
documented with production remediation paths.
