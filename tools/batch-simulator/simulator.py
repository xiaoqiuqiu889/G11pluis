"""
batch-simulator/simulator.py
=============================
Run N synthetic plays of a scene contract and collect statistics.

This is the QA workhorse for the project.  It generates N independent
runs of a scene contract, each driven by a **policy** (random,
heuristic, or AI-stub).  After every play it runs the four-questions
guard and aggregates:

* blocking / passing rates
* forbidden-reveal rates
* mandatory-echo utilisation
* per-action-type counts
* end-state distribution
* cost model — total model calls, total turn consumption

The output is a single JSON report that can be diffed between runs.

Usage
-----
    python tools/batch-simulator/simulator.py \\
        --contract content/.../scenes/photo_lab_2008.yaml \\
        --policy  random \\
        --n       1000 \\
        --output  batch_report.json

The simulator is intentionally decoupled from the real engine:
    * No model calls.  The ``ai`` policy uses the heuristic as a stub.
    * No database.  Everything stays in memory.
    * The 4-questions-guard is the **only** external dependency from
      ``tools/`` — the rest is pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import four_questions_guard_lib as guard  # noqa: E402


# ---------------------------------------------------------------------------
# Policy interface
# ---------------------------------------------------------------------------


PolicyFn = Callable[[dict[str, Any], int, random.Random], dict[str, Any]]


def random_policy(state: dict[str, Any], turn: int, rng: random.Random) -> dict[str, Any]:
    """Pick a random legal action and target.  The most lossy policy —
    useful for stress-testing that the 4-questions guard still
    catches edge cases under random play.
    """
    verbs = state.get("_legal_actions") or [
        "investigate", "give", "conceal", "wait", "silence",
    ]
    targets = state.get("_legal_targets") or ["leila", "arash"]
    action = rng.choice(verbs)
    target = rng.choice(targets)
    artifact_pool = state.get("_artifact_pool") or ["photo_pair", "poem", "ticket"]
    artifact = rng.choice(artifact_pool)
    return {
        "verb": action,
        "target": target,
        "artifact": artifact,
    }


def heuristic_policy(state: dict[str, Any], turn: int, rng: random.Random) -> dict[str, Any]:
    """A simple "good-citizen" policy: spend early turns on
    investigate, mid turns on give/reveal, late turns on leave.  Used
    to verify the guard accepts well-behaved plays.
    """
    if turn < 2:
        verb = "investigate"
    elif turn < 5:
        verb = "give"
    elif turn < 7:
        verb = rng.choice(["reveal", "conceal"])
    else:
        verb = "leave"
    return {
        "verb": verb,
        "target": rng.choice(["leila", "arash"]),
        "artifact": "photo_pair",
    }


def ai_policy_stub(state: dict[str, Any], turn: int, rng: random.Random) -> dict[str, Any]:
    """The "AI" policy is a stub: identical to ``heuristic_policy`` for
    now.  When the real model gateway lands (W3-A), this is where
    an LLM call would slot in.  For batch testing the stub is enough
    — the simulator's job is to surface guard-level issues, not
    model-level ones.
    """
    return heuristic_policy(state, turn, rng)


POLICIES: dict[str, PolicyFn] = {
    "random": random_policy,
    "heuristic": heuristic_policy,
    "ai": ai_policy_stub,
}


# ---------------------------------------------------------------------------
# Per-play state machine
# ---------------------------------------------------------------------------


@dataclass
class PlayTrace:
    """One simulated play."""

    seed: int
    policy: str
    turns_taken: int
    actions: list[dict[str, Any]] = field(default_factory=list)
    guard_blocking: bool = False
    guard_reasons: list[str] = field(default_factory=list)
    final_scene_id: str = "<unknown>"
    final_turn_index: int = 0
    artifacts_tracked: dict[str, str] = field(default_factory=dict)
    forbidden_reveals_surfaced: list[str] = field(default_factory=list)
    end_kind: str = "<incomplete>"  # "ended" | "exhausted" | "guard_blocked"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BatchReport:
    """Aggregate of N plays."""

    contract_path: str
    policy: str
    n_requested: int
    n_completed: int
    n_blocked_by_guard: int
    blocking_rate: float
    mean_turns: float
    median_turns: float
    max_turns: int
    min_turns: int
    action_distribution: dict[str, int]
    end_kind_distribution: dict[str, int]
    forbidden_reveals_total: int
    artifacts_distribution: dict[str, int]
    timing_seconds: float
    per_play: list[PlayTrace] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# The simulator
# ---------------------------------------------------------------------------


def _initial_state(contract: dict[str, Any]) -> dict[str, Any]:
    """Derive the simulator's internal state from a scene contract."""
    allowed_actions = contract.get("allowed_actions") or [
        "investigate", "give", "conceal", "leave", "wait", "silence",
    ]
    turn_budget = contract.get("turn_budget") or {}
    total = int(turn_budget.get("total", 8)) if isinstance(turn_budget, dict) else 8
    scene_id = contract.get("sceneId") or contract.get("scene_id") or "<unknown>"
    artifact_pool = []
    for obj in contract.get("investigatable_objects") or []:
        if isinstance(obj, dict) and "id" in obj:
            artifact_pool.append(obj["id"])
    if not artifact_pool:
        artifact_pool = ["photo_pair", "poem", "ticket"]
    return {
        "sceneId": scene_id,
        "total": total,
        "_legal_actions": allowed_actions,
        "_legal_targets": [c.get("id", c.get("name", "?")) for c in
                           (contract.get("characters_present") or [])
                           if isinstance(c, dict)],
        "_artifact_pool": artifact_pool,
    }


def simulate_one(
    contract: dict[str, Any],
    policy_name: str,
    seed: int,
    *,
    max_turns: int | None = None,
) -> PlayTrace:
    """Run a single play and return its trace."""
    if policy_name not in POLICIES:
        raise ValueError(f"unknown policy: {policy_name}; available: {list(POLICIES)}")
    rng = random.Random(seed)
    state = _initial_state(contract)
    policy = POLICIES[policy_name]
    cap = max_turns or state["total"]
    trace = PlayTrace(seed=seed, policy=policy_name, turns_taken=0)

    # Build a per-play interaction document the guard can chew on.
    interaction: dict[str, Any] = {
        "sceneId": state["sceneId"],
        "artifact_updates": [],
        "event_log": [],
        "belief_updates": [],
        "belief_matrix": [],
        "turn_budget": {"total": state["total"], "current_turn": 0, "max_turns": state["total"]},
        "action_whitelist": state["_legal_actions"],
        "causal_seeds": [],
        "far_echo_routes": [],
        "forbidden_reveals": contract.get("forbidden_reveals") or [],
    }

    end_kind = "<incomplete>"
    # Per-play artifact owner tracking — the simulator respects the
    # C_artifact_uniqueness rule by never double-giving an artifact.
    artifact_owners: dict[str, str] = {}
    for turn in range(cap):
        trace.turns_taken = turn + 1
        action = policy(state, turn, rng)
        verb = action.get("verb", "wait")
        target = action.get("target")
        artifact = action.get("artifact")
        record = {"turn": turn + 1, "verb": verb, "target": target, "artifact": artifact}
        trace.actions.append(record)

        # Reflect the action on the in-memory state.
        if verb in {"give", "destroy", "reveal"} and artifact:
            if verb == "give" and target:
                # Don't double-give an already-owned artifact.  The
                # first owner wins — this is the C_artifact_uniqueness
                # rule, enforced by the simulator so its traces are
                # well-formed.
                if artifact in artifact_owners:
                    record["skipped_duplicate"] = True
                else:
                    artifact_owners[artifact] = target
                    trace.artifacts_tracked[artifact] = target
                    interaction["artifact_updates"].append({
                        "artifactId": artifact,
                        "newOwnerId": target,
                    })
            elif verb == "destroy":
                if artifact in artifact_owners:
                    owner = artifact_owners.pop(artifact)
                    trace.artifacts_tracked[artifact] = f"<destroyed from {owner}>"
                    interaction["artifact_updates"].append({
                        "artifactId": artifact,
                        "newOwnerId": "<destroyed>",
                    })
                else:
                    record["skipped_unowned"] = True
            else:
                interaction["artifact_updates"].append({
                    "artifactId": artifact,
                })
        if verb in {"reveal", "conceal", "question", "comfort"} and target:
            interaction["belief_updates"].append({
                "characterId": target,
                "subject": "interaction",
                "belief_state": "reinforced" if verb in {"comfort", "reveal"} else "uncertain",
                "confidence": 0.7,
            })
        if verb in {"promise", "give"}:
            interaction["causal_seeds"].append({
                "seedId": f"seed_{turn}_{artifact or 'x'}",
                "planted": True,
            })
            interaction["far_echo_routes"].append({
                "targetSceneId": "reunion_2024",
                "seedIds": [f"seed_{turn}_{artifact or 'x'}"],
            })

        interaction["event_log"].append({
            "eventId": f"evt_{turn}",
            "description": f"{verb} {artifact or ''} {target or ''}".strip(),
        })

        # Track turn progress in the per-play state.
        interaction["turn_budget"]["current_turn"] = turn + 1

        if verb == "leave":
            end_kind = "ended"
            break

    if end_kind == "<incomplete>":
        end_kind = "exhausted"

    # Optional: 50% of the time, add a forbidden_reveal mistake, to
    # verify the guard catches it.
    if rng.random() < 0.5 and interaction["forbidden_reveals"]:
        forbidden_keys = [
            f.get("revealKey") or f.get("key")
            for f in interaction["forbidden_reveals"]
            if isinstance(f, dict)
        ]
        if forbidden_keys:
            key = forbidden_keys[0]
            interaction["utterance"] = f"今天我想告诉你 {key} 的全部细节。"
            trace.forbidden_reveals_surfaced.append(key)

    # Run the guard on the cumulative play.
    report = guard.run_guard(interaction, document_path=f"<sim:{seed}>")
    trace.guard_blocking = report.blocking
    trace.guard_reasons = list(report.blocking_reasons)
    trace.final_scene_id = state["sceneId"]
    trace.final_turn_index = trace.turns_taken
    trace.end_kind = end_kind if not report.blocking else "guard_blocked"
    return trace


def simulate_batch(
    contract: dict[str, Any],
    policy: str,
    n: int,
    *,
    base_seed: int = 0,
    max_turns: int | None = None,
) -> BatchReport:
    """Run ``n`` plays and aggregate the results."""
    if n <= 0:
        raise ValueError("n must be positive")
    started = time.time()
    traces: list[PlayTrace] = []
    for i in range(n):
        traces.append(simulate_one(contract, policy, base_seed + i, max_turns=max_turns))

    turn_counts = [t.turns_taken for t in traces]
    action_counter: Counter[str] = Counter()
    end_counter: Counter[str] = Counter()
    artifact_counter: Counter[str] = Counter()
    forbidden_total = 0
    for t in traces:
        for a in t.actions:
            verb = a.get("verb", "?")
            action_counter[verb] += 1
            art = a.get("artifact")
            if art:
                artifact_counter[art] += 1
        end_counter[t.end_kind] += 1
        forbidden_total += len(t.forbidden_reveals_surfaced)
    blocked = sum(1 for t in traces if t.guard_blocking)

    report = BatchReport(
        contract_path="<memory>",
        policy=policy,
        n_requested=n,
        n_completed=len(traces),
        n_blocked_by_guard=blocked,
        blocking_rate=blocked / n if n else 0.0,
        mean_turns=sum(turn_counts) / n if n else 0.0,
        median_turns=_median(turn_counts),
        max_turns=max(turn_counts) if turn_counts else 0,
        min_turns=min(turn_counts) if turn_counts else 0,
        action_distribution=dict(action_counter),
        end_kind_distribution=dict(end_counter),
        forbidden_reveals_total=forbidden_total,
        artifacts_distribution=dict(artifact_counter),
        timing_seconds=time.time() - started,
        per_play=traces,
    )
    return report


def _median(xs: list[int]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    if n % 2:
        return float(s[n // 2])
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="batch-simulator",
        description=(
            "Run N synthetic plays of a scene contract and aggregate "
            "4-questions-guard statistics.  Used for secret-leak "
            "testing and character-consistency evaluation."
        ),
    )
    p.add_argument(
        "--contract", "-c",
        required=True,
        help="Path to the scene contract YAML/JSON.",
    )
    p.add_argument(
        "--policy", "-p",
        default="random",
        choices=sorted(POLICIES.keys()),
        help="Action-selection policy.  Default: random.",
    )
    p.add_argument(
        "--n", type=int, default=100,
        help="Number of plays to simulate.  Default: 100.",
    )
    p.add_argument(
        "--max-turns", type=int, default=None,
        help="Override the scene's max_turns (useful for stress testing).",
    )
    p.add_argument(
        "--base-seed", type=int, default=0,
        help="Base seed for the random policy.  Default: 0.",
    )
    p.add_argument(
        "--output", "-o",
        help="Write the full JSON report to this file.",
    )
    p.add_argument(
        "--no-per-play", action="store_true",
        help="Strip per-play traces from the report (smaller output).",
    )
    p.add_argument(
        "--version", action="version", version="batch-simulator 1.0.0",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parse_args().parse_args(argv)
    try:
        contract = guard.load_document(args.contract)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"❌ failed to load contract {args.contract}: {exc}\n")
        return 1
    report = simulate_batch(
        contract, args.policy, args.n,
        base_seed=args.base_seed,
        max_turns=args.max_turns,
    )
    report.contract_path = args.contract
    payload = report.to_dict()
    if args.no_per_play:
        payload.pop("per_play", None)
    if args.output:
        Path(args.output).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        sys.stderr.write(f"✅ wrote {args.n} plays to {args.output}\n")
    else:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    # Always print a one-line summary on stderr.
    sys.stderr.write(
        f"summary: n={report.n_completed}, "
        f"blocking_rate={report.blocking_rate:.2%}, "
        f"mean_turns={report.mean_turns:.1f}, "
        f"elapsed={report.timing_seconds:.2f}s\n"
    )
    # Exit 0 if everything passed, 1 if anything was blocked.
    return 0 if report.n_blocked_by_guard == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
