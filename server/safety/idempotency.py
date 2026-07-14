"""Idempotency — the replay-key gate.

The Resolver guarantees that the same input, replayed, produces
the same outcome (and never advances the world state twice).
Two surfaces implement the guarantee:

* ``idempotencyKey`` — the composite hash the Resolver stamps
  on every event.  Replays of the same key are no-ops.
* ``clientActionId`` — the per-action UUID the client stamps
  on every action.  Replays of the same id are no-ops.

The engine itself enforces both at write time
(:exc:`IdempotencyReplayError`); this module is the **audit**
surface that catches violations *before* the engine does, so
the safety layer can reject a misbehaving LLM output that
claims to be a replay but uses an unknown key.

Exit codes (for the CLI)
------------------------

* ``0``  — pass, no duplicates
* ``1``  — block: at least one duplicate detected
* ``2``  — I/O error: log file unreadable, malformed JSON, etc.

The CLI (``tools/idempotency_check.py``) and CI workflow
both read these codes; tests assert on them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class ExitCode(int, Enum):
    """Stable exit codes for the CLI / CI surface."""

    PASS = 0
    BLOCK = 1
    IO_ERROR = 2


# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class IdempotencyViolation:
    """One duplicate-detection row."""

    key: str
    key_kind: str  # "idempotencyKey" or "clientActionId"
    first_seen_at: int  # index in the log
    duplicate_at: int
    sequence: int | None = None
    actorId: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class IdempotencyReport:
    """Aggregate result of an idempotency audit."""

    passed: bool
    exit_code: int
    log_size: int
    violations: list[IdempotencyViolation] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "exit_code": int(self.exit_code),
            "log_size": self.log_size,
            "violations": [v.to_dict() for v in self.violations],
            "summary": dict(self.summary),
        }

    def to_human_readable(self) -> str:
        lines: list[str] = []
        verdict = "✅ PASS" if self.passed else "❌ BLOCK"
        lines.append(f"{verdict}  idempotency  exit_code={int(self.exit_code)}  log_size={self.log_size}")
        s = self.summary
        lines.append(
            "summary: "
            + ", ".join(f"{k}={v}" for k, v in s.items() if v)
        )
        for v in self.violations:
            lines.append(
                f"  • [{v.key_kind}] {v.key[:16]}… "
                f"first={v.first_seen_at} dup={v.duplicate_at} "
                f"seq={v.sequence} actor={v.actorId}"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# The checker
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def audit_idempotency_keys(event_log: list[dict[str, Any]]) -> IdempotencyReport:
    """Audit a list of event-log entries for duplicate idempotencyKeys.

    Parameters
    ----------
    event_log : list[dict]
        The events.  Each entry must have at least
        ``idempotencyKey`` (string) and ``sequence`` (int).

    Returns
    -------
    IdempotencyReport
        ``passed`` is False iff at least one duplicate was
        found; ``exit_code`` follows :class:`ExitCode` (0/1/2).
        The function never raises on a well-formed input.
    """

    violations: list[IdempotencyViolation] = []
    seen: dict[str, int] = {}
    for i, ev in enumerate(event_log):
        if not isinstance(ev, dict):
            continue
        key = ev.get("idempotencyKey", "")
        if not key:
            continue
        if key in seen:
            violations.append(IdempotencyViolation(
                key=key,
                key_kind="idempotencyKey",
                first_seen_at=seen[key],
                duplicate_at=i,
                sequence=ev.get("sequence"),
                actorId=ev.get("actorId"),
            ))
        else:
            seen[key] = i
    summary = {
        "idempotencyKey_duplicates": len(violations),
        "unique_idempotencyKeys": len(seen),
    }
    return IdempotencyReport(
        passed=not violations,
        exit_code=int(ExitCode.PASS if not violations else ExitCode.BLOCK),
        log_size=len(event_log),
        violations=violations,
        summary=summary,
    )


def scan_client_action_replays(
    event_log: list[dict[str, Any]],
    *,
    seen_window: int | None = None,
) -> IdempotencyReport:
    """Scan a log for duplicate ``clientActionId`` values.

    The Resolver uses the ``actionPayload.clientActionId`` field
    of each event to dedupe on the client side.  This audit
    replays that check on a loaded log so a corrupt / hand-edited
    log is caught.

    Parameters
    ----------
    event_log : list[dict]
        The events.
    seen_window : int | None
        Optional cap on how many of the most recent events to
        scan.  When ``None`` (the default) every event is
        scanned.  Tests use a small window to verify the
        cap works.
    """

    violations: list[IdempotencyViolation] = []
    seen: dict[str, int] = {}
    start = 0
    if seen_window is not None and seen_window > 0 and len(event_log) > seen_window:
        start = len(event_log) - seen_window
    for i in range(start, len(event_log)):
        ev = event_log[i]
        if not isinstance(ev, dict):
            continue
        payload = ev.get("actionPayload") or {}
        if not isinstance(payload, dict):
            continue
        client_aid = payload.get("clientActionId")
        if not client_aid:
            continue
        if client_aid in seen:
            violations.append(IdempotencyViolation(
                key=client_aid,
                key_kind="clientActionId",
                first_seen_at=seen[client_aid],
                duplicate_at=i,
                sequence=ev.get("sequence"),
                actorId=ev.get("actorId"),
            ))
        else:
            seen[client_aid] = i

    summary = {
        "clientActionId_duplicates": len(violations),
        "unique_clientActionIds": len(seen),
    }
    return IdempotencyReport(
        passed=not violations,
        exit_code=int(ExitCode.PASS if not violations else ExitCode.BLOCK),
        log_size=len(event_log),
        violations=violations,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# File I/O — used by the CLI and CI
# ---------------------------------------------------------------------------


def load_log(path: str | Path) -> list[dict[str, Any]]:
    """Load an event log from disk (JSON) and return the list of events.

    Accepts two on-disk shapes:

    * Plain list — ``[ {event}, {event}, ... ]``
    * Wrapper    — ``{"runId": "...", "events": [...]}``

    Raises
    ------
    FileNotFoundError
        The path does not exist.
    json.JSONDecodeError
        The file is not valid JSON.
    ValueError
        The file does not contain a list of events.
    """

    p = Path(path)
    with open(p, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict)]
    if isinstance(data, dict):
        events = data.get("events", [])
        if not isinstance(events, list):
            raise ValueError(f"unexpected log shape: {type(events).__name__}")
        return [e for e in events if isinstance(e, dict)]
    raise ValueError(f"unexpected top-level type: {type(data).__name__}")


def audit_file(
    path: str | Path,
    *,
    check_replays: bool = True,
    replay_window: int | None = None,
) -> IdempotencyReport:
    """Read a log file and run both audits (keys + replays).

    Returns
    -------
    IdempotencyReport
        The combined report.  Exit code is the worst of the
        two audits: BLOCK if either audit found a duplicate,
        IO_ERROR only if the file could not be read.
    """

    try:
        events = load_log(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return IdempotencyReport(
            passed=False,
            exit_code=int(ExitCode.IO_ERROR),
            log_size=0,
            violations=[],
            summary={"io_error": 1, "total": 1},
        )

    key_report = audit_idempotency_keys(events)
    if not check_replays:
        return key_report

    replay_report = scan_client_action_replays(events, seen_window=replay_window)

    # Merge: the worst exit code wins, violations are concatenated
    combined_violations = list(key_report.violations) + list(replay_report.violations)
    summary = {
        "idempotencyKey_duplicates": key_report.summary.get("idempotencyKey_duplicates", 0),
        "clientActionId_duplicates": replay_report.summary.get("clientActionId_duplicates", 0),
        "unique_idempotencyKeys": key_report.summary.get("unique_idempotencyKeys", 0),
        "unique_clientActionIds": replay_report.summary.get("unique_clientActionIds", 0),
        "total": len(combined_violations),
    }
    exit_code = int(
        ExitCode.BLOCK if combined_violations
        else ExitCode.PASS
    )
    return IdempotencyReport(
        passed=not combined_violations,
        exit_code=exit_code,
        log_size=key_report.log_size,
        violations=combined_violations,
        summary=summary,
    )


__all__ = [
    "ExitCode",
    "IdempotencyViolation",
    "IdempotencyReport",
    "audit_idempotency_keys",
    "scan_client_action_replays",
    "load_log",
    "audit_file",
]
