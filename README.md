# scada-sim

A water treatment plant simulation I built to get hands-on with industrial
control system security.

The simulation runs [Factory.io](https://factoryio.com/) (an industrial
simulation tool) under Wine on Linux, with a real Modbus TCP connection to a
Python backend. Everything is containerised.

---

## What it does

- **Fills and drains a water tank** using Modbus-controlled valves
- **Streams live sensor data** (tank level, flow rate, setpoint) to a React
  HMI dashboard that updates every 2 seconds
- **Fires process alarms** when levels hit defined thresholds — high/high-high
  for overflow risk, low/low-low for pump cavitation risk
- **Stores all readings** in InfluxDB so you can view historical trends
- **Lets operators control valves** from the HMI, protected by API key auth

---

## Stack

```
Browser → OWASP ModSecurity WAF → nginx (React HMI) → FastAPI backend → Modbus TCP → Factory.io
                                                              └──────────────────────→ InfluxDB
```

| Component | Technology | Why |
|-----------|-----------|-----|
| Industrial simulation | Factory.io + Wine | Real Modbus server, actual PLC register map |
| Backend | Python / FastAPI | Async Modbus polling, REST API, historian writes |
| Protocol | Modbus TCP (pymodbus) | The real protocol used in water/energy SCADA |
| Historian | InfluxDB 2 | Time-series database purpose-built for sensor data |
| HMI | React + Vite + Tailwind + Recharts | Live dashboard, alarm panel, trend charts |
| WAF | OWASP ModSecurity CRS | Blocks OWASP Top 10 before requests hit the app |
| CI/CD | GitHub Actions | Gitleaks, Semgrep, Trivy, OWASP ZAP on every push |

---

## Security features

**Static analysis (every push):**
- **Gitleaks** — scans git history for accidentally committed secrets
- **Semgrep** — SAST with OWASP Top 10 rules plus custom ICS-specific rules
  (hardcoded Modbus hosts, unauthenticated writes, mock mode in production)
- **Trivy** — scans the Docker image for CVEs in OS packages and Python deps

**Dynamic testing (every push to trunk):**
- **OWASP ZAP** — spins up the backend in mock mode and fires real HTTP
  requests at every endpoint, checking for exploitable vulnerabilities

**Runtime controls:**
- OWASP ModSecurity WAF with Core Rule Set blocks SQLi, XSS, command injection
- API key authentication with `secrets.compare_digest` (timing-attack safe)
- Rate limiting on all endpoints
- Security headers on every response (CSP, HSTS, X-Frame-Options, CORP, etc.)
- Non-root Docker containers
- iptables restricts Modbus port 502 to the Docker bridge subnet only

**Dependency management:**
- Dependabot monitors Python packages, npm packages, Docker base images, and
  GitHub Actions — raises PRs within 24 hours of a CVE patch being released

---

## Security documentation

The `docs/` folder contains the security design documentation:

- **[Threat Model](docs/threat-model.md)** — STRIDE analysis of every
  component, trust zones, and documented accepted risks
- **[Essential Eight Mapping](docs/essential8-mapping.md)** — maps controls
  to the ASD Essential Eight with honest maturity level assessments
- **[AESCSF Mapping](docs/aescsf-mapping.md)** — maps controls to the
  Australian Energy Sector Cyber Security Framework (Identify, Protect,
  Detect, Respond, Recover)

---

## Factory.io Modbus register map

If you want to connect your own Factory.io scene, here's what the backend expects:

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

---

## CI/CD pipeline status

The security pipeline runs automatically on every push:

| Check | Trigger | Fail condition |
|-------|---------|---------------|
| Gitleaks | Every push | Committed secret found |
| Semgrep | Every push | Insecure code pattern found |
| Trivy | Every push | HIGH/CRITICAL CVE with available fix |
| OWASP ZAP | Push to trunk | Exploitable vulnerability found |
| Dependabot | Daily | Opens PRs for outdated dependencies |
