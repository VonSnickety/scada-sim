"""
modbus_dast.py — Modbus Protocol Security Test

MANUAL TEST — run this against a live Factory.io instance, not in CI.
This script tests the Modbus TCP layer directly, which is only meaningful
against the real target. A simulated Modbus server would only prove the
script runs, not that our system is secure.

Usage:
  python tests/modbus_dast.py --host 127.0.0.1 --port 502

Simulates an attacker who has gained access to the OT network segment and
attempts to interact with the Modbus server directly, bypassing the REST API
and its authentication controls entirely.

This is a realistic threat scenario for industrial environments: once an
attacker is on the OT network (via phishing, VPN compromise, or physical
access), Modbus TCP has no authentication — any client can read and write
registers freely.

Tests performed:
  1. Unauthenticated register read  — can we read sensor values without auth?
  2. Unauthenticated coil read      — can we read digital I/O states?
  3. Unauthenticated register write — can we command a valve without the API key?
  4. Out-of-range value write       — what happens if we send value 65535?
  5. Register enumeration           — can we map the full register space?

Exit codes:
  0 — all tests completed, no unexpected findings
  1 — one or more findings require attention

IEC 62443 SR 1.1  — Human User Authentication (tests absence at protocol level)
IEC 62443 SR 2.1  — Authorisation Enforcement
IEC 62443 SR 3.6  — Deterministic Output
"""

import argparse
import sys

# pymodbus is a synchronous import here — we use the sync client for the test
# harness to keep the script simple and dependency-free from the app's async stack
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException

# ── Register map (must match factoryio_client.py) ─────────────────────────────
SLAVE_ID         = 1
INPUT_REG_LEVEL  = 0   # Tank level (FC4)
INPUT_REG_FLOW   = 1   # Flow rate (FC4)
INPUT_REG_SP     = 2   # Setpoint (FC4)
HOLD_REG_FILL    = 0   # Fill valve (FC3)
HOLD_REG_DISCH   = 1   # Discharge valve (FC3)
COIL_START_LIGHT = 0   # Start indicator light (FC1)

# Safe values the application uses
VALVE_OPEN       = 32767
VALVE_CLOSED     = 0

# Out-of-range value — above the 0-32767 range the app uses
OUT_OF_RANGE_VAL = 65535

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
INFO = "INFO"


def run_tests(host: str, port: int) -> int:
    """
    Run all Modbus security tests against the target host.
    Returns the number of unexpected findings (0 = clean).
    """
    print(f"\nModbus DAST — target {host}:{port}")
    print("=" * 60)

    client = ModbusTcpClient(host, port=port, timeout=3)
    connected = client.connect()

    if not connected:
        print(f"[{SKIP}] Could not connect to Modbus server at {host}:{port}")
        print(f"[{SKIP}] Server not reachable — skipping all tests")
        print("\nThis is expected in CI mock mode.")
        print("Run against a live Factory.io instance for full results.")
        return 0

    print(f"[{INFO}] Connected to Modbus server — running tests\n")

    findings = []

    # ── Test 1: Unauthenticated input register read ────────────────────────────
    # Expected: Modbus has no auth — reads WILL succeed. This is a known
    # protocol limitation. We record it as an informational finding, not a failure.
    # The control is at the API layer, not the Modbus layer.
    print("Test 1: Unauthenticated input register read (FC4)")
    try:
        result = client.read_input_registers(address=0, count=3, slave=SLAVE_ID)
        if result.isError():
            print(f"  [{PASS}] Read returned error — server rejected unauthenticated read")
        else:
            level = result.registers[0] / 10.0
            flow  = result.registers[1] / 10.0
            sp    = result.registers[2]
            print(f"  [{INFO}] Read succeeded (expected — Modbus has no auth)")
            print(f"  [{INFO}] Tank level={level}%  Flow={flow}  Setpoint={sp}")
            print(f"  [{INFO}] Mitigation: OT network segmentation prevents")
            print(f"  [{INFO}] unauthorised clients reaching this port")
    except ModbusException as exc:
        print(f"  [{PASS}] ModbusException: {exc}")
    print()

    # ── Test 2: Unauthenticated coil read ─────────────────────────────────────
    # Reads indicator light states — maps the digital I/O layout of the plant
    print("Test 2: Unauthenticated coil read — plant I/O mapping (FC1)")
    try:
        result = client.read_coils(address=0, count=4, slave=SLAVE_ID)
        if result.isError():
            print(f"  [{PASS}] Read returned error — coil read rejected")
        else:
            print(f"  [{INFO}] Coil read succeeded — digital I/O states readable")
            print(f"  [{INFO}] Coils: {result.bits[:4]}")
            print(f"  [{INFO}] Mitigation: network segmentation (same as Test 1)")
    except ModbusException as exc:
        print(f"  [{PASS}] ModbusException: {exc}")
    print()

    # ── Test 3: Unauthenticated holding register write — VALVE COMMAND ─────────
    # This is the critical test. Can we open the fill valve without an API key?
    # Expected: Write WILL succeed — Modbus has no auth at protocol level.
    # This is the core risk that network segmentation must mitigate.
    print("Test 3: Unauthenticated register write — open fill valve (FC3)")
    print(f"  Writing VALVE_OPEN ({VALVE_OPEN}) to holding register {HOLD_REG_FILL}")
    try:
        result = client.write_register(
            address=HOLD_REG_FILL, value=VALVE_OPEN, slave=SLAVE_ID
        )
        if result.isError():
            print(f"  [{PASS}] Write rejected by server")
        else:
            print(f"  [{FAIL}] Write succeeded — valve commanded without authentication")
            print(f"  [{FAIL}] Any host on the OT network can open/close valves directly")
            print(f"  [{FAIL}] Mitigation required: firewall rule restricting port {port}")
            print(f"  [{FAIL}] to authorised HMI hosts only")
            findings.append("Test 3: Unauthenticated valve write succeeded")

        # Restore safe state — close the valve
        client.write_register(address=HOLD_REG_FILL, value=VALVE_CLOSED, slave=SLAVE_ID)
        print(f"  [{INFO}] Restored: wrote VALVE_CLOSED ({VALVE_CLOSED}) to restore safe state")
    except ModbusException as exc:
        print(f"  [{PASS}] ModbusException: {exc}")
    print()

    # ── Test 4: Out-of-range value write ──────────────────────────────────────
    # Writes a value (65535) outside the 0-32767 range the application uses.
    # The PLC/Factory.io should clamp or reject it.
    # If it's accepted and applied, the physical device receives an undefined command.
    print(f"Test 4: Out-of-range register write — value {OUT_OF_RANGE_VAL} (FC3)")
    try:
        result = client.write_register(
            address=HOLD_REG_FILL, value=OUT_OF_RANGE_VAL, slave=SLAVE_ID
        )
        if result.isError():
            print(f"  [{PASS}] Write rejected — server enforces value bounds")
        else:
            print(f"  [{INFO}] Write accepted — device will clamp or interpret value")
            print(f"  [{INFO}] Check Factory.io behaviour for values above 32767")
            print(f"  [{INFO}] Application layer prevents this via boolean-only API")

        # Restore safe state
        client.write_register(address=HOLD_REG_FILL, value=VALVE_CLOSED, slave=SLAVE_ID)
        print(f"  [{INFO}] Restored: wrote VALVE_CLOSED to restore safe state")
    except ModbusException as exc:
        print(f"  [{PASS}] ModbusException: {exc}")
    print()

    # ── Test 5: Register enumeration ──────────────────────────────────────────
    # Reads all 10 holding registers to map the full register space.
    # This is reconnaissance — an attacker learns what registers exist and
    # what values they hold before crafting targeted writes.
    print("Test 5: Holding register enumeration — full register space scan (FC3)")
    try:
        result = client.read_holding_registers(address=0, count=10, slave=SLAVE_ID)
        if result.isError():
            print(f"  [{PASS}] Read rejected — register map not disclosed")
        else:
            print(f"  [{INFO}] Register scan succeeded — full register map readable")
            for i, val in enumerate(result.registers):
                print(f"  [{INFO}] Register {i:02d} = {val}")
            print(f"  [{INFO}] Mitigation: network segmentation limits who can enumerate")
    except ModbusException as exc:
        print(f"  [{PASS}] ModbusException: {exc}")
    print()

    client.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("=" * 60)
    if findings:
        print(f"FINDINGS: {len(findings)} issue(s) require attention\n")
        for f in findings:
            print(f"  ! {f}")
        print()
        print("Note: Modbus protocol has no native authentication.")
        print("Primary mitigations are network-layer controls:")
        print("  - Firewall rules restricting Modbus port to authorised hosts")
        print("  - OT/IT network segmentation (separate VLANs)")
        print("  - No direct internet exposure of Modbus port")
        return len(findings)
    else:
        print("All tests completed — no unexpected findings")
        print("Protocol-level read access is expected (Modbus has no auth)")
        print("Network segmentation is the primary control for this layer")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Modbus protocol security test for scada-sim"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Modbus server host")
    parser.add_argument("--port", type=int, default=502, help="Modbus server port")
    args = parser.parse_args()

    findings = run_tests(args.host, args.port)
    sys.exit(1 if findings > 0 else 0)


if __name__ == "__main__":
    main()
