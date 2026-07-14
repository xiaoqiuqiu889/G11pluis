"""
replay-lab/cli.py
=================
Command-line interface for the replay-lab.

Usage
-----
    # Replay a run from an event log:
    python -m tools.replay-lab.cli \\
        --snapshot path/to/snapshot.json \\
        --events   path/to/events.yaml \\
        --output   path/to/replay.json

    # Pretty-print the trace on stderr:
    python -m tools.replay-lab.cli \\
        --snapshot snapshot.json \\
        --events   events.yaml \\
        --human

    # Replay only up to eventSequence=10:
    python -m tools.replay-lab.cli \\
        --snapshot snapshot.json \\
        --events   events.yaml \\
        --stop-at 10

    # Build a synthetic event log from inline JSON:
    python -m tools.replay-lab.cli \\
        --events -  <<< '[{"eventSequence": 0, "outcomeId": "..."}]'

Notes
-----
* The snapshot is optional.  When omitted, a minimal initial snapshot
  is fabricated (``replay.make_initial_snapshot``) with a fresh
  runId.  This is useful for unit-testing a delta in isolation.
* The output is always written as JSON.  When ``--human`` is given,
  a human-readable trace is also printed on stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import four_questions_guard_lib as guard  # noqa: E402
import replay  # noqa: E402


def _parse_args() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="replay-lab",
        description=(
            "Snapshot replay tool for 《革命街没有尽头》.  Loads a "
            "world snapshot and an event log, walks the events in "
            "order, and produces a final snapshot + per-event trace."
        ),
    )
    p.add_argument(
        "--snapshot",
        help=(
            "Path to the initial world snapshot (JSON or YAML).  "
            "If omitted, a synthetic snapshot is fabricated."
        ),
    )
    p.add_argument(
        "--events",
        required=True,
        help="Path to the event log (JSON or YAML).  Use '-' for stdin.",
    )
    p.add_argument(
        "--output", "-o",
        help="Write the replay result to this file (JSON).  Default: stdout.",
    )
    p.add_argument(
        "--human",
        action="store_true",
        help="Print a human-readable trace on stderr.",
    )
    p.add_argument(
        "--stop-at",
        type=int,
        help="Halt the replay once eventSequence >= STOP_AT.",
    )
    p.add_argument(
        "--run-id",
        help="Override the runId on the final snapshot.",
    )
    p.add_argument(
        "--guard",
        action="store_true",
        help=(
            "Run the four-questions-guard on each event in the log and "
            "include the guard result in the trace.  Useful for bulk "
            "adversarial testing of a run."
        ),
    )
    p.add_argument(
        "--version",
        action="version",
        version="replay-lab 1.0.0",
    )
    return p


def _load_snapshot(path: str | None) -> dict[str, Any]:
    if path is None:
        return replay.make_initial_snapshot()
    return guard.load_document(path)


def _load_events(path: str) -> list[replay.EventLogEntry]:
    if path == "-":
        text = sys.stdin.read()
        if not text.strip():
            raise SystemExit("event log from stdin is empty")
        # Try JSON, fall back to YAML.
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            import yaml  # type: ignore
            data = yaml.safe_load(text)
        if not isinstance(data, list):
            raise SystemExit(
                f"event log from stdin must be a list, got {type(data).__name__}"
            )
        return [_entry_from_dict(item) for item in data]
    return replay.load_event_log(path)


def _entry_from_dict(item: dict[str, Any]) -> replay.EventLogEntry:
    if not isinstance(item, dict):
        raise ValueError(f"event must be a mapping, got {type(item).__name__}")
    return replay._entry_from_dict(item)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args().parse_args(argv)

    try:
        snapshot = _load_snapshot(args.snapshot)
        events = _load_events(args.events)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"❌ load failed: {exc}\n")
        return 1

    result = replay.replay(
        snapshot, events, runId=args.run_id, stop_at=args.stop_at,
    )

    if args.guard:
        # Decorate each trace entry with the guard verdict for its
        # corresponding event.  This makes the replay-lab double as a
        # bulk 4-questions CI driver.
        for ev, trace_entry in zip(events, result.trace):
            # Build a synthetic interaction document from the event.
            interaction_doc = {
                "artifact_updates": ev.artifact_updates,
                "event_log": ev.event_log,
                "belief_updates": ev.belief_updates,
                "belief_matrix": ev.raw.get("belief_matrix", []),
                "turn_budget": {
                    "current_turn": ev.turn_index,
                    "max_turns": ev.raw.get("max_turns"),
                } if ev.turn_index is not None else {},
                "action_whitelist": ev.raw.get("action_whitelist", []),
                "causal_seeds": ev.causal_seeds,
                "far_echo_routes": ev.raw.get("far_echo_routes", []),
            }
            report = guard.run_guard(
                interaction_doc,
                document_path=f"event:{ev.eventSequence}",
            )
            trace_entry.applied.append(
                f"guard:{'PASS' if not report.blocking else 'BLOCK'}"
            )
            if report.blocking:
                trace_entry.skipped.extend(report.blocking_reasons)

    payload = result.to_dict()

    if args.output:
        Path(args.output).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        sys.stderr.write(f"✅ wrote replay to {args.output}\n")
    else:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")

    if args.human:
        sys.stderr.write(_format_human_trace(result) + "\n")
        sys.stderr.write(
            f"summary: {result.events_applied} applied, "
            f"{result.events_skipped} skipped, "
            f"final eventSequence = {result.final_event_sequence}\n"
        )

    return 0 if result.events_skipped == 0 else 1


def _format_human_trace(result: replay.ReplayResult) -> str:
    lines: list[str] = []
    lines.append(f"Replay for runId={result.runId}")
    lines.append(f"  events: {result.events_applied} applied, {result.events_skipped} skipped")
    for tr in result.trace:
        scene = tr.sceneId or "-"
        action = tr.actionType or "-"
        lines.append(f"  [{tr.eventSequence:>4}] {scene:>22} / {action:<10}")
        for label in tr.applied:
            lines.append(f"      ✓ {label}")
        for skipped in tr.skipped:
            lines.append(f"      ✗ {skipped}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
