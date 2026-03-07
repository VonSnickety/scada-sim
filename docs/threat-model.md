# Threat Model — SCADA Simulation Water Treatment Plant

## Overview

This document applies STRIDE threat modelling to the scada-sim water treatment
plant simulation. The goal is to systematically identify what could go wrong,
who might cause it, and what controls are in place — or knowingly accepted as risk.

STRIDE is used here because it maps well to ICS/SCADA environments and aligns
with IEC 62443 security requirements. Each finding is also tagged to OWASP API
Security Top 10 where applicable.

---

## System Architecture

```
                    INTERNET / OPERATOR BROWSER
                              │
                              ▼
                   ┌─────────────────────┐
                   │   OWASP ModSecurity  │  WAF — blocks OWASP Top 10
                   │   (CRS nginx)        │  before requests reach the app
                   │   port 80            │
                   └──────────┬──────────┘
                              │ HTTP (internal Docker network)
                              ▼
                   ┌─────────────────────┐
                   │   React HMI         │  nginx serving static files
                   │   (nginx:alpine)    │  No server-side logic here
                   └──────────┬──────────┘
                              │ /api/* proxied (internal Docker network)
                              ▼
                   ┌─────────────────────┐
                   │   FastAPI Backend   │  API key auth on control endpoints
                   │   (python:slim)     │  Rate limiting, security headers
                   │   port 8000         │  Input validation via Pydantic
                   └──────┬──────┬───────┘
                          │      │
              Modbus TCP  │      │  InfluxDB write (HTTP)
              port 502    │      │
                          ▼      ▼
               ┌──────────────┐  ┌───────────────────┐
               │  Factory.io  │  │    InfluxDB 2      │
               │  (Wine/host) │  │  time-series DB    │
               │  Modbus slave│  │  historian data    │
               └──────────────┘  └───────────────────┘
```

### Trust Zones

| Zone | Components | Trust Level |
|------|-----------|-------------|
| External | Browser, operator workstation | Untrusted |
| DMZ | WAF | Semi-trusted (filters external) |
| Application | Frontend nginx, Backend FastAPI | Trusted |
| OT Network | Factory.io Modbus, InfluxDB | Highly trusted (no auth by design) |

The most critical boundary is **Application → OT Network**. Modbus has no
authentication — anything that reaches port 502 can read sensors and write
actuators. Access control must be enforced at the application layer.

---

## Threat Actors

| Actor | Motivation | Capability |
|-------|-----------|-----------|
| External attacker | Data theft, disruption | Low–Medium (public internet) |
| Malicious insider | Sabotage, fraud | High (network access) |
| Script kiddie | Opportunistic | Low (automated scanners) |
| Nation-state (notional) | Critical infrastructure disruption | Very High |

For this simulation environment, the primary realistic threats are external
attacker and script kiddie. The nation-state actor is included for completeness
as water treatment is classified critical infrastructure under the SOCI Act 2018.

---

## STRIDE Analysis

### Component: WAF (OWASP ModSecurity)

| STRIDE | Threat | Control | Residual Risk |
|--------|--------|---------|---------------|
| **S** Spoofing | Attacker spoofs trusted IP to bypass WAF rules | WAF rules are based on request content, not IP | Low — CRS rules are signature-based |
| **T** Tampering | WAF config modified to disable rules | Config is in Docker image, requires container rebuild | Low |
| **R** Repudiation | Attacker denies sending malicious requests | ModSecurity logs all blocked requests with client IP | Low |
| **I** Info Disclosure | WAF version/config exposed in response headers | `Server` header suppressed by ModSecurity | Low |
| **D** DoS | Flood of requests exhausts WAF capacity | Rate limiting enforced at backend layer (slowapi) | Medium — no connection-level rate limit at WAF |
| **E** Elevation | WAF bypass via encoding/evasion | CRS PARANOIA=1; could increase to 2–3 for production | Medium |

### Component: FastAPI Backend

| STRIDE | Threat | Control | Residual Risk |
|--------|--------|---------|---------------|
| **S** Spoofing | Operator API key stolen and reused | `secrets.compare_digest` prevents timing attacks; key should be rotated regularly | Medium — no MFA, single factor only |
| **T** Tampering | Valve command payload modified in transit | HTTPS should be enforced in production (HSTS header present) | Medium — HTTP used in dev/lab |
| **R** Repudiation | Operator denies issuing a valve command | All control commands logged with `request.client.host` and command value | Medium — IP logging, no user identity |
| **I** Info Disclosure | `/api/state` exposes live sensor data publicly | Accepted risk (I-01) — operators need frictionless monitoring; no PII involved | Low — plant state only, no credentials |
| **D** DoS | Slowloris / request flood crashes uvicorn | `slowapi` rate limiting: 60 req/min on `/api/state` | Medium — single-instance, no clustering |
| **E** Elevation | Read-only user escalates to control access | Auth enforced via `Depends(verify_api_key)` on all POST endpoints | Low |

**Accepted Risk I-01:** `/api/state` and `/api/alarms` are unauthenticated.
Rationale: operators must be able to view plant status without friction; a
locked-out operator is a safety risk. Sensor data has no PII and limited
value to an attacker. This mirrors real SCADA HMI design where read access
is typically unrestricted on the operations network.

### Component: Modbus TCP (Factory.io)

| STRIDE | Threat | Control | Residual Risk |
|--------|--------|---------|---------------|
| **S** Spoofing | Attacker sends crafted Modbus frames directly to port 502 | iptables restricts port 502 to Docker bridge subnet only (172.18.0.0/16) | Medium — relies on correct iptables config |
| **T** Tampering | Man-in-the-middle modifies Modbus register values | Modbus TCP has no integrity checking by design | **HIGH** — protocol limitation, accepted risk |
| **R** Repudiation | Modbus write cannot be attributed to specific user | Backend logs all writes before issuing Modbus command | Medium — log is at API layer, not protocol layer |
| **I** Info Disclosure | Modbus allows reading all registers with no auth | Only accessible from application subnet; iptables blocks external access | Low in this architecture |
| **D** DoS | Modbus request flood crashes Factory.io | iptables limits exposure; no rate limiting at Modbus layer | Medium |
| **E** Elevation | Any host on Docker network can write to Modbus | Network segmentation (Docker bridge); backend is the only Modbus client | Low |

**Note on Modbus tampering:** This is an inherent protocol limitation — Modbus
was designed in 1979 for isolated serial networks and has no cryptographic
integrity. In production water treatment, this is mitigated by:
- Physical network isolation (air gap or dedicated OT VLAN)
- Encrypted tunnels (MACsec, IPsec) over any shared medium
- OPC-UA with security mode `SignAndEncrypt` as a modern alternative

### Component: InfluxDB Historian

| STRIDE | Threat | Control | Residual Risk |
|--------|--------|---------|---------------|
| **S** Spoofing | Attacker writes fake historical data | Admin token required; token in env var not source code | Low |
| **T** Tampering | Historical records modified or deleted | Token-based write access; InfluxDB audit log available | Low |
| **R** Repudiation | Cannot determine who wrote a data point | All writes come from backend service; no per-user attribution | Medium |
| **I** Info Disclosure | InfluxDB UI exposed on port 8086 | Port 8086 only accessible locally (not mapped externally in production) | Low |
| **D** DoS | Historian write loop fills disk | `ignore-unfixed` pattern; historian failure is non-fatal to API | Low |
| **E** Elevation | InfluxDB admin token used to modify org/buckets | Token scoped to write bucket; admin token not used at runtime | Low |

---

## Top Risks Summary

| ID | Component | Threat | Severity | Mitigation Status |
|----|-----------|--------|----------|-------------------|
| T-01 | Modbus | Tampering — no integrity checking | HIGH | Accepted (protocol limitation) |
| T-02 | Backend | DoS — no connection-level rate limit | MEDIUM | Partial (slowapi at app layer) |
| T-03 | Backend | Spoofing — single-factor API key | MEDIUM | Accepted (lab scope) |
| T-04 | WAF | Elevation — CRS evasion possible | MEDIUM | Partial (PARANOIA=1) |
| T-05 | Backend | Tampering — HTTP in dev (no TLS) | MEDIUM | Accepted (lab scope; HSTS header present) |

---

## Residual Risk Acceptance

The following risks are accepted for this simulation/lab environment and would
require additional controls before production deployment:

1. **TLS termination** — All traffic should be encrypted in transit. In
   production, a reverse proxy (nginx/Traefik) with valid TLS certificate
   should terminate HTTPS before the WAF.

2. **Modbus network isolation** — Port 502 should be on a dedicated OT VLAN
   with no route to the IT network. The iptables rule used here is a
   reasonable simulation but not equivalent to physical segmentation.

3. **Operator identity** — The current auth model uses a shared API key with
   no individual user identity. Production should use individual credentials
   with RBAC and full audit trail (who opened which valve, when).

4. **High availability** — Single-instance FastAPI is a DoS risk. Production
   would require load balancing and health-checked replicas.

---

## References

- [IEC 62443-3-3](https://www.iec.ch/homepage) — System Security Requirements
- [OWASP API Security Top 10](https://owasp.org/API-Security/)
- [NIST SP 800-82](https://csrc.nist.gov/publications/detail/sp/800-82/rev-3/final) — Guide to ICS Security
- [ACSC Essential Eight](https://www.cyber.gov.au/resources-business-and-government/essential-cyber-security/essential-eight)
- [AESCSF](https://www.energycouncil.com.au/initiatives/aescsf/) — Australian Energy Sector Cyber Security Framework
