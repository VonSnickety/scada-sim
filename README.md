# scada-sim

A water treatment plant simulation I built to get hands-on with industrial
control system security. Rather than reading about SCADA vulnerabilities in
theory, I wanted to actually run a plant, watch sensors change in real time,
and understand what it takes to secure the stack properly.

The simulation runs [Factory.io](https://factoryio.com/) (an industrial
simulation tool) under Wine on Linux, with a real Modbus TCP connection to a
Python backend — the same protocol used in actual water treatment facilities.
Everything is containerised with Docker Compose and sits behind an OWASP WAF.

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

This project is as much about the security layer as the simulation itself.

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

## Running it

You'll need Factory.io installed (Windows or Wine on Linux) with the Modbus
driver configured. See the register map below.

**Prerequisites:**
- Docker + Docker Compose
- Wine with Factory.io (or set `MOCK_MODE=true` to run without it)

**Setup:**

```bash
# Copy and fill in the env file
cp backend/.env.example backend/.env
# Edit backend/.env with your API key and InfluxDB token

# Copy root env for Docker Compose secrets
cp backend/.env.example .env
# Edit .env with the same InfluxDB token and admin password
```

**Start everything (Factory.io + full Docker stack):**

```bash
./start.sh
```

This applies the iptables rule for Docker→Modbus connectivity, launches
Factory.io under Wine, waits for it to initialise, then brings up the stack.

**Or run in mock mode (no Factory.io needed):**

```bash
MOCK_MODE=true docker compose up
```

The HMI is at `http://localhost` and the API at `http://localhost:8000/api/state`.

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

## Why Modbus has no authentication

Modbus was designed in 1979 for isolated serial networks — security was never
part of the spec. There's no authentication, no encryption, no integrity
checking. Anyone who can reach port 502 can read every sensor and write to
every actuator.

In real water treatment facilities this is mitigated by physical network
isolation (dedicated OT VLANs with no route to corporate IT), encrypted
tunnels over any shared medium, and — increasingly — modern protocols like
OPC-UA which support authentication and encryption natively.

This project documents that gap honestly in the threat model rather than
pretending it doesn't exist.

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
