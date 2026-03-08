# scada-sim

A weekend project to get hands-on with OT security and application security CI/CD
practices. Simulates a water treatment plant using real industrial protocols, then
layers security controls and automated scanning on top.

Not production infrastructure — the goal was to build something realistic enough
that the security problems are interesting.

---

## What it does

- **Fills and drains a water tank** via Modbus TCP-controlled valves connected to a
  Factory.io 3D plant simulation
- **Streams live sensor data** (tank level, flow rate, setpoint) to a React HMI
  dashboard that updates every 2 seconds
- **Fires process alarms** when values cross thresholds — high/high-high for overflow
  risk, low/low-low for pump cavitation risk, and a no-flow alarm when the fill valve
  is open but flow reads zero for 3 consecutive polls
- **Alarm acknowledgement** — operators can acknowledge active alarms via the HMI;
  acknowledgement persists across polls while the condition is active
- **Audit log** — every actuator command and alarm acknowledgement is recorded with
  timestamp, actor IP, and outcome; accessible via authenticated API endpoint
- **Stores all readings** in InfluxDB for historical trend views
- **Lets operators control valves** from the HMI, protected by API key auth

---

## Stack

```
Browser → nginx (React HMI) → FastAPI backend → Modbus TCP → Factory.io
                                    └──────────────────────→ InfluxDB
```

| Component | Technology |
|-----------|-----------|
| Industrial simulation | Factory.io + Wine on Linux |
| Backend | Python / FastAPI |
| Protocol | Modbus TCP (pymodbus) |
| Historian | InfluxDB 2 |
| HMI | React + Vite + Tailwind + Recharts |
| CI/CD | GitHub Actions |

---

## Security features

**CI pipeline (every push):**
- **Gitleaks** — scans git history for accidentally committed secrets
- **Semgrep** — SAST with OWASP Top 10 rules plus 7 custom ICS-specific rules:
  hardcoded Modbus hosts, unauthenticated Modbus writes, unbounded register values,
  mock mode hardcoded in production, hardcoded API keys, POST endpoints missing
  authentication, and control endpoints missing audit logging
- **Trivy** — scans the Docker image for CVEs in OS packages and Python dependencies
- **OWASP ZAP** — spins up the backend in mock mode and probes every endpoint
  for exploitable vulnerabilities using the OpenAPI spec

**Runtime controls:**
- API key authentication with `secrets.compare_digest` (timing-attack safe)
- Rate limiting on all endpoints via slowapi
- Security headers on every response (CSP, HSTS, X-Frame-Options, CORP, etc.)
- Audit log for all control-plane actions (OWASP A09, IEC 62443 SR 2.8)
- Non-root Docker containers
- Dependabot monitors Python, npm, Docker base images, and GitHub Actions

---

## Security documentation

The `docs/` folder contains the security design documentation:

- **[Threat Model](docs/threat-model.md)** — STRIDE analysis, trust zones, accepted risks
- **[Essential Eight Mapping](docs/essential8-mapping.md)** — ASD Essential Eight with honest maturity assessments
- **[AESCSF Mapping](docs/aescsf-mapping.md)** — Australian Energy Sector Cyber Security Framework mapping

---

## Intentional failure branches

Three open PRs demonstrate the CI pipeline catching real vulnerability classes:

| Branch | Scanner | What it demonstrates |
|--------|---------|---------------------|
| `test/trivy-vulnerable-dependency` | Trivy | Pinned dependency with known CVEs |
| `test/semgrep-missing-auth-and-audit` | Semgrep | POST endpoint missing both auth and audit logging — two custom rules firing simultaneously |
| `test/zap-reflected-parameter` | OWASP ZAP | Reflected query parameter with `fail_action` enabled |

---

## Factory.io Modbus register map

| Register type | Address | Value | Description |
|--------------|---------|-------|-------------|
| Input Register (FC4) | 0 | 0–1000 | Tank level (÷10 = %) |
| Input Register (FC4) | 1 | 0–1000 | Flow rate (÷10) |
| Input Register (FC4) | 2 | 0–1000 | Setpoint |
| Discrete Input (FC2) | 0 | 0/1 | Start button |
| Discrete Input (FC2) | 2 | 0/1 | Stop button |
| Discrete Input (FC2) | 3 | 0/1 | Running status |
| Holding Register (FC3) | 0 | 0 / 32767 | Fill valve (0=closed, 32767=open) |
| Holding Register (FC3) | 1 | 0 / 32767 | Discharge valve |
