"""
test_alarms.py — Unit tests for alarm logic and audit log

These tests verify the security-relevant behaviour of the plant monitoring
system without needing Factory.io, InfluxDB, or any network connection.

Every test here maps to a real failure mode:
  - Wrong threshold  → operator misses a critical event
  - Debounce broken  → alarm spam desensitises operators (alarm fatigue)
  - Ack not persisted → acknowledged alarms re-appear as new, confusing operators
  - Audit log wrong  → security audit trail is unreliable
"""

import pytest
from app.factoryio_client import (
    Alarm,
    FactoryIOClient,
    TANK_HIGH_CRIT,
    TANK_HIGH_WARN,
    TANK_LOW_CRIT,
    TANK_LOW_WARN,
    FLOW_NO_FLOW_TICKS,
)
from app.audit import AuditLog


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_client(tank_level=50.0, flow_rate=10.0, fill_valve_open=False) -> FactoryIOClient:
    """Create a FactoryIOClient with preset state — no Modbus connection needed."""
    client = FactoryIOClient()
    client.state.tank_level = tank_level
    client.state.flow_rate = flow_rate
    client.state.fill_valve_open = fill_valve_open
    return client


# ── Tank level alarm thresholds ───────────────────────────────────────────────

class TestTankLevelAlarms:

    def test_no_alarm_in_normal_range(self):
        """Mid-range level — no alarms should fire."""
        client = make_client(tank_level=50.0)
        alarms = client._evaluate_alarms()
        assert alarms == []

    def test_high_warn_fires_at_threshold(self):
        """Level exactly at TANK_HIGH_WARN boundary — HIGH alarm fires."""
        client = make_client(tank_level=TANK_HIGH_WARN)
        alarms = client._evaluate_alarms()
        ids = [a.id for a in alarms]
        assert "T001_HIGH" in ids

    def test_high_crit_fires_above_crit_threshold(self):
        """Level above TANK_HIGH_CRIT — CRIT alarm fires, not just HIGH."""
        client = make_client(tank_level=TANK_HIGH_CRIT + 1)
        alarms = client._evaluate_alarms()
        ids = [a.id for a in alarms]
        assert "T001_HH" in ids
        assert "T001_HIGH" not in ids  # CRIT supersedes HIGH

    def test_high_crit_severity_is_crit(self):
        client = make_client(tank_level=95.0)
        alarms = client._evaluate_alarms()
        crit = next(a for a in alarms if a.id == "T001_HH")
        assert crit.severity == "CRIT"

    def test_low_warn_fires_at_threshold(self):
        """Level exactly at TANK_LOW_WARN boundary — WARN alarm fires."""
        client = make_client(tank_level=TANK_LOW_WARN)
        alarms = client._evaluate_alarms()
        ids = [a.id for a in alarms]
        assert "T001_LOW" in ids

    def test_low_crit_fires_below_crit_threshold(self):
        """Level below TANK_LOW_CRIT — CRIT alarm fires, not just WARN."""
        client = make_client(tank_level=TANK_LOW_CRIT - 1)
        alarms = client._evaluate_alarms()
        ids = [a.id for a in alarms]
        assert "T001_LL" in ids
        assert "T001_LOW" not in ids  # CRIT supersedes WARN

    def test_low_crit_severity_is_crit(self):
        client = make_client(tank_level=5.0)
        alarms = client._evaluate_alarms()
        crit = next(a for a in alarms if a.id == "T001_LL")
        assert crit.severity == "CRIT"

    def test_just_below_high_warn_no_alarm(self):
        """One decimal below the high warn threshold — no alarm."""
        client = make_client(tank_level=TANK_HIGH_WARN - 0.1)
        alarms = client._evaluate_alarms()
        assert not any(a.id in ("T001_HIGH", "T001_HH") for a in alarms)

    def test_just_above_low_warn_no_alarm(self):
        """One decimal above the low warn threshold — no alarm."""
        client = make_client(tank_level=TANK_LOW_WARN + 0.1)
        alarms = client._evaluate_alarms()
        assert not any(a.id in ("T001_LOW", "T001_LL") for a in alarms)


# ── Flow rate alarm debouncing ────────────────────────────────────────────────

class TestFlowNoFlowAlarm:
    """
    The FLOW_NO_FLOW alarm uses a tick counter to debounce noisy sensor readings.
    It must not fire until FLOW_NO_FLOW_TICKS consecutive zero-flow polls have
    occurred with the fill valve open.

    Why this matters: a single zero-flow reading can be a sensor glitch.
    Firing immediately causes alarm fatigue — operators start ignoring alarms.
    Only sustained zero-flow indicates a real fault (blocked pipe, sensor failure).
    """

    def test_no_alarm_when_valve_closed(self):
        """Zero flow with valve closed is normal — no alarm."""
        client = make_client(flow_rate=0.0, fill_valve_open=False)
        for _ in range(FLOW_NO_FLOW_TICKS + 1):
            alarms = client._evaluate_alarms()
        assert not any(a.id == "FLOW_NO_FLOW" for a in alarms)

    def test_no_alarm_before_tick_threshold(self):
        """Valve open, zero flow, but not enough ticks yet — no alarm."""
        client = make_client(flow_rate=0.0, fill_valve_open=True)
        for _ in range(FLOW_NO_FLOW_TICKS - 1):
            alarms = client._evaluate_alarms()
        assert not any(a.id == "FLOW_NO_FLOW" for a in alarms)

    def test_alarm_fires_at_tick_threshold(self):
        """Valve open, zero flow, exactly FLOW_NO_FLOW_TICKS polls — alarm fires."""
        client = make_client(flow_rate=0.0, fill_valve_open=True)
        for _ in range(FLOW_NO_FLOW_TICKS):
            alarms = client._evaluate_alarms()
        assert any(a.id == "FLOW_NO_FLOW" for a in alarms)

    def test_alarm_clears_when_flow_resumes(self):
        """Flow resumes after alarm — alarm clears and tick counter resets."""
        client = make_client(flow_rate=0.0, fill_valve_open=True)
        for _ in range(FLOW_NO_FLOW_TICKS):
            client._evaluate_alarms()

        # Flow resumes
        client.state.flow_rate = 10.0
        alarms = client._evaluate_alarms()
        assert not any(a.id == "FLOW_NO_FLOW" for a in alarms)
        assert client._zero_flow_ticks == 0

    def test_tick_counter_resets_on_valve_close(self):
        """Valve closes mid-count — tick counter resets, alarm does not fire."""
        client = make_client(flow_rate=0.0, fill_valve_open=True)
        for _ in range(FLOW_NO_FLOW_TICKS - 1):
            client._evaluate_alarms()

        client.state.fill_valve_open = False
        alarms = client._evaluate_alarms()
        assert not any(a.id == "FLOW_NO_FLOW" for a in alarms)
        assert client._zero_flow_ticks == 0

    def test_flow_no_flow_severity_is_high(self):
        client = make_client(flow_rate=0.0, fill_valve_open=True)
        for _ in range(FLOW_NO_FLOW_TICKS):
            alarms = client._evaluate_alarms()
        alarm = next(a for a in alarms if a.id == "FLOW_NO_FLOW")
        assert alarm.severity == "HIGH"


# ── Alarm acknowledgement ─────────────────────────────────────────────────────

class TestAlarmAcknowledgement:
    """
    Acknowledgement must persist across polls for as long as the condition is
    active. If it doesn't, every poll creates a new unacknowledged alarm and
    the operator has to keep re-acknowledging — which breaks the workflow and
    masks new alarms from the same source.
    """

    def test_acknowledged_flag_persists_on_next_poll(self):
        """Ack a high-level alarm — next poll should still show it as acknowledged."""
        client = make_client(tank_level=95.0)

        # First poll — alarm fires unacknowledged
        alarms = client._evaluate_alarms()
        assert any(a.id == "T001_HH" for a in alarms)

        # Operator acknowledges
        client.state.alarms = alarms
        for a in client.state.alarms:
            if a.id == "T001_HH":
                a.acknowledged = True

        # Second poll — condition still active, ack should persist
        alarms = client._evaluate_alarms()
        alarm = next(a for a in alarms if a.id == "T001_HH")
        assert alarm.acknowledged is True

    def test_acknowledgement_clears_when_condition_resolves(self):
        """Tank drops back to normal — alarm disappears entirely, not just unacked."""
        client = make_client(tank_level=95.0)
        alarms = client._evaluate_alarms()
        client.state.alarms = alarms
        for a in client.state.alarms:
            a.acknowledged = True

        # Condition resolves
        client.state.tank_level = 50.0
        alarms = client._evaluate_alarms()
        assert not any(a.id == "T001_HH" for a in alarms)

    def test_new_alarm_starts_unacknowledged(self):
        """Different alarm fires after ack — new alarm is unacknowledged."""
        client = make_client(tank_level=95.0)
        alarms = client._evaluate_alarms()
        client.state.alarms = alarms
        for a in client.state.alarms:
            a.acknowledged = True

        # Now tank drops critically low (different alarm ID)
        client.state.tank_level = 5.0
        alarms = client._evaluate_alarms()
        low_alarm = next((a for a in alarms if a.id == "T001_LL"), None)
        assert low_alarm is not None
        assert low_alarm.acknowledged is False


# ── Audit log ─────────────────────────────────────────────────────────────────

class TestAuditLog:

    def test_record_adds_entry(self):
        log = AuditLog()
        log.record(action="fill_valve_open", actor="10.0.0.1", outcome="success")
        assert len(log.recent()) == 1

    def test_recent_returns_newest_first(self):
        """Newest entries must appear first — operators need latest events at the top."""
        log = AuditLog()
        log.record(action="fill_valve_open", actor="10.0.0.1", outcome="success")
        log.record(action="fill_valve_close", actor="10.0.0.1", outcome="success")
        log.record(action="discharge_valve_open", actor="10.0.0.1", outcome="success")

        entries = log.recent()
        assert entries[0]["action"] == "discharge_valve_open"
        assert entries[-1]["action"] == "fill_valve_open"

    def test_recent_respects_limit(self):
        log = AuditLog()
        for i in range(20):
            log.record(action=f"action_{i}", actor="10.0.0.1", outcome="success")
        assert len(log.recent(limit=5)) == 5

    def test_failure_outcome_recorded_with_detail(self):
        log = AuditLog()
        log.record(
            action="fill_valve_open",
            actor="10.0.0.1",
            outcome="failure",
            detail="Not connected to Factory.io",
        )
        entry = log.recent()[0]
        assert entry["outcome"] == "failure"
        assert "Not connected" in entry["detail"]

    def test_max_entries_enforced(self):
        """Audit log must not grow unbounded — oldest entries dropped at MAX_ENTRIES."""
        log = AuditLog()
        for i in range(AuditLog.MAX_ENTRIES + 50):
            log.record(action=f"action_{i}", actor="10.0.0.1", outcome="success")
        assert len(log.recent(limit=AuditLog.MAX_ENTRIES + 50)) == AuditLog.MAX_ENTRIES

    def test_entry_has_utc_timestamp(self):
        log = AuditLog()
        log.record(action="test", actor="10.0.0.1", outcome="success")
        entry = log.recent()[0]
        # ISO format with timezone offset
        assert "T" in entry["timestamp"]
        assert "+" in entry["timestamp"] or entry["timestamp"].endswith("Z") or "+00:00" in entry["timestamp"]
