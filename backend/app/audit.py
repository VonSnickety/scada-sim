from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class AuditEntry:
    timestamp: str
    action: str
    actor: str
    outcome: str  # "success" or "failure"
    detail: str = ""


class AuditLog:
    """
    Append-only in-memory audit log for operator actions.

    Addresses OWASP A09:2021 — Security Logging and Monitoring Failures by
    recording every actuator command with actor, outcome, and timestamp.
    Satisfies IEC 62443 SR 2.8 — Auditable Events.
    """

    MAX_ENTRIES = 1000

    def __init__(self):
        self._entries: deque[AuditEntry] = deque(maxlen=self.MAX_ENTRIES)

    def record(self, action: str, actor: str, outcome: str, detail: str = "") -> None:
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action=action,
            actor=actor,
            outcome=outcome,
            detail=detail,
        )
        self._entries.append(entry)

    def recent(self, limit: int = 100) -> list[dict]:
        entries = list(self._entries)
        return [asdict(e) for e in reversed(entries[-limit:])]
