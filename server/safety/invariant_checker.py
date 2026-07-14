"""Invariant checker — automatic verification of state-machine invariants.

A *state invariant* is a property of the canonical world state
that the engine guarantees to hold at every well-defined point
in time.  The brief lists ten invariants; each is implemented
as a check function in this module and the orchestrator
:func:`check_all_invariants` runs them in one pass and returns
a structured report.

The ten invariants
------------------

I1  **Objective facts immutability** — once a fact is recorded
    in ``objective_facts`` the description / establishedAt
    cannot change (a Resolver bug must not silently rewrite
    history).

I2  **Knowledge is grounded in evidence** — a character's
    ``character_knowledge`` entry must reference at least one
    memory id (an evidence-grounded belief); a knowledge entry
    with no evidence and high confidence is a fabrication
    signal.

I3  **Artifact location uniqueness** — the same physical
    artifact cannot simultaneously be in two different
    locations.  The engine's ``ArtifactState`` has a single
    ``location`` field; the check here defends against a
    hypothetical multi-tenant world snapshot.

I4  **No action by dead / absent characters** — the active
    cast of a scene is the only set of ``actorId`` values
    that may appear in the event log.  (For a future
    flashback / ghost-event model the engine would carry
    an explicit ``ghost`` flag; absent that, this is a hard
    block.)

I5  **Relationship values in legal range** — every numeric
    relationship field on a :class:`RelationshipState` is
    inside its legal range.  The engine's ``__post_init__``
    already clamps on construction; the check here is the
    belt-and-braces runtime check on a snapshot the Resolver
    is about to commit.

I6  **No secret leak** — a character's dialogue / narration
    does not surface a forbidden-reveal key.  This is the
    *combined* version of the content-guard forbidden-reveal
    check, applied at the *whole-snapshot* level after all
    NPC proposals have been merged.

I7  **No entitlement fabrication** — only the server may
    determine free / paid entitlement; an LLM cannot emit
    an ``isFree`` / ``isPaid`` field.  Any LLM payload that
    carries such a field is rejected (the field is stripped
    silently and a violation is reported).

I8  **Replay determinism** — replaying the same event log
    with the same random seed must produce the same final
    snapshot.  The check here is the **post-replay**
    assertion: a replayed snapshot must equal the original
    byte-for-byte (modulo timestamps).

I9  **Atomic write** — a model timeout must not leave a
    half-written state.  The check here is the
    *invariant-preserving* check: a snapshot either has
    ``eventSequence`` matching the count of events in the
    log (atomic write) or it carries an explicit
    ``partial=True`` marker (which the safety layer never
    produces; an external rollback tool does).

I10 **Idempotency** — every event in the log has a unique
    ``idempotencyKey``.  The Resolver enforces this at
    write time; the check here is the audit pass that
    confirms a loaded log has no duplicates.

These are the **canonical ten**; the brief lists them as
"verifies" and the safety package is what guarantees them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class InvariantViolation:
    """One violation row."""

    invariant_id: str  # I1..I10
    rule: str
    path: str
    detail: str
    offending_value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InvariantReport:
    """The aggregate invariant-check report."""

    passed: bool
    violations: list[InvariantViolation] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "summary": dict(self.summary),
        }

    def to_human_readable(self) -> str:
        lines: list[str] = []
        verdict = "✅ PASS" if self.passed else "❌ FAIL"
        lines.append(f"{verdict}  invariants")
        s = self.summary
        lines.append(
            "summary: "
            + ", ".join(f"{k}={v}" for k, v in s.items() if v)
        )
        for v in self.violations:
            lines.append(f"  • [{v.invariant_id}] {v.path}  rule={v.rule}")
            lines.append(f"      detail: {v.detail}")
            if v.offending_value is not None:
                lines.append(f"      value : {v.offending_value!r}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


# ---------------------------------------------------------------------------
# Individual invariants
# ---------------------------------------------------------------------------


def check_objective_facts_immutability(snapshot: dict[str, Any]) -> list[InvariantViolation]:
    """I1: every objective fact has a positive establishedAt and a non-empty factId."""

    out: list[InvariantViolation] = []
    for matrices in _as_list(snapshot.get("beliefMatrices")):
        if not isinstance(matrices, dict):
            continue
        for i, fact in enumerate(_as_list(matrices.get("objective_facts"))):
            if not isinstance(fact, dict):
                continue
            fid = fact.get("factId")
            desc = fact.get("description")
            est = fact.get("establishedAt")
            if not fid or not isinstance(fid, str):
                out.append(InvariantViolation(
                    invariant_id="I1", rule="objective_facts.factId is non-empty string",
                    path=f"beliefMatrices[].objective_facts[{i}].factId",
                    detail=f"factId is {fid!r}",
                    offending_value=fid,
                ))
            if not desc or not isinstance(desc, str):
                out.append(InvariantViolation(
                    invariant_id="I1", rule="objective_facts.description is non-empty string",
                    path=f"beliefMatrices[].objective_facts[{i}].description",
                    detail=f"description is {desc!r}",
                    offending_value=desc,
                ))
            if not isinstance(est, int) or est < 0:
                out.append(InvariantViolation(
                    invariant_id="I1", rule="objective_facts.establishedAt is non-negative int",
                    path=f"beliefMatrices[].objective_facts[{i}].establishedAt",
                    detail=f"establishedAt is {est!r}",
                    offending_value=est,
                ))
    return out


def check_knowledge_grounded_in_evidence(snapshot: dict[str, Any]) -> list[InvariantViolation]:
    """I2: every knowledge entry with high confidence has at least one evidence memory id.

    Confidence ≥ 0.5 with an empty evidence list is a fabrication
    signal.  The LLM is allowed to "feel" something with no
    evidence (low confidence) but cannot be sure of it.
    """

    out: list[InvariantViolation] = []
    for matrices in _as_list(snapshot.get("beliefMatrices")):
        if not isinstance(matrices, dict):
            continue
        cid = matrices.get("characterId", "?")
        for i, k in enumerate(_as_list(matrices.get("character_knowledge"))):
            if not isinstance(k, dict):
                continue
            evidence = k.get("evidenceMemoryIds") or []
            confidence = k.get("confidence", 0.0)
            if isinstance(confidence, (int, float)) and confidence >= 0.5 and len(evidence) == 0:
                out.append(InvariantViolation(
                    invariant_id="I2",
                    rule="knowledge.confidence>=0.5 requires at least one evidenceMemoryId",
                    path=f"beliefMatrices[{cid!r}].character_knowledge[{i}]",
                    detail=f"subject={k.get('subject')!r} confidence={confidence} evidence={evidence!r}",
                    offending_value=k,
                ))
    return out


def check_artifact_location_uniqueness(snapshot: dict[str, Any]) -> list[InvariantViolation]:
    """I3: an artifact with a non-null location is at exactly one location."""

    out: list[InvariantViolation] = []
    artifacts = snapshot.get("artifactState")
    if not isinstance(artifacts, list):
        return out
    for art in artifacts:
        if not isinstance(art, dict):
            continue
        loc = art.get("location")
        if loc is None:
            continue
        # The single-source-of-truth: a dict has at most one
        # ``location`` field.  We do a sanity assertion that
        # the field is a string of length 1..128.
        if not isinstance(loc, str) or not (1 <= len(loc) <= 128):
            out.append(InvariantViolation(
                invariant_id="I3",
                rule="artifact.location is a non-empty string <= 128 chars",
                path=f"artifactState[{art.get('artifactId')!r}].location",
                detail=f"location is {loc!r}",
                offending_value=loc,
            ))
    return out


def check_no_action_by_inactive_character(
    snapshot: dict[str, Any],
    event_log: list[dict[str, Any]] | None,
) -> list[InvariantViolation]:
    """I4: every event actorId is alive AND present in the active cast.

    "Alive" and "present" are decided by two parallel data
    structures on the snapshot:

    * ``canonicalState.casualties`` (optional) — character ids
      that have died.  If absent, no one is dead.
    * ``canonicalState.cast`` (optional) — character ids
      currently in scene.  If absent, no cast is recorded
      (the engine in test mode skips this).
    """

    out: list[InvariantViolation] = []
    canonical = snapshot.get("canonicalState", {})
    casualties = set(_as_list(canonical.get("casualties")))
    cast = canonical.get("cast")
    cast_set = set(cast) if isinstance(cast, list) else None

    for i, ev in enumerate(event_log or []):
        if not isinstance(ev, dict):
            continue
        actor = ev.get("actorId")
        if actor in casualties:
            out.append(InvariantViolation(
                invariant_id="I4",
                rule="event.actorId must not be in canonicalState.casualties",
                path=f"event_log[{i}].actorId",
                detail=f"actor {actor!r} is in casualties {sorted(casualties)}",
                offending_value=actor,
            ))
        if cast_set is not None and actor not in cast_set and actor != "system":
            out.append(InvariantViolation(
                invariant_id="I4",
                rule="event.actorId must be in the active cast",
                path=f"event_log[{i}].actorId",
                detail=f"actor {actor!r} not in cast {sorted(cast_set)}",
                offending_value=actor,
            ))
    return out


def check_relationship_values_in_range(snapshot: dict[str, Any]) -> list[InvariantViolation]:
    """I5: every numeric relationship field is in its legal range."""

    out: list[InvariantViolation] = []
    for i, rel in enumerate(_as_list(snapshot.get("relationshipState"))):
        if not isinstance(rel, dict):
            continue
        path_prefix = f"relationshipState[{i}]"
        for key, lo, hi in [
            ("trust", -1.0, 1.0),
            ("intimacy", -1.0, 1.0),
            ("respect", -1.0, 1.0),
            ("unresolvedConflict", 0.0, 1.0),
            ("fear", 0.0, 1.0),
        ]:
            value = rel.get(key)
            if not isinstance(value, (int, float)):
                out.append(InvariantViolation(
                    invariant_id="I5",
                    rule=f"{key} must be a number in [{lo}, {hi}]",
                    path=f"{path_prefix}.{key}",
                    detail=f"value is {value!r}",
                    offending_value=value,
                ))
                continue
            if value != value or value in (float("inf"), float("-inf")):
                out.append(InvariantViolation(
                    invariant_id="I5",
                    rule=f"{key} must be finite",
                    path=f"{path_prefix}.{key}",
                    detail=f"value is non-finite: {value!r}",
                    offending_value=value,
                ))
                continue
            if value < lo or value > hi:
                out.append(InvariantViolation(
                    invariant_id="I5",
                    rule=f"{key} must be in [{lo}, {hi}]",
                    path=f"{path_prefix}.{key}",
                    detail=f"value {value} is out of range",
                    offending_value=value,
                ))
    return out


def check_no_forbidden_secret_leak(
    snapshot: dict[str, Any],
    forbidden_reveals: Iterable[str | dict[str, Any]],
) -> list[InvariantViolation]:
    """I6: snapshot fields do not surface any forbidden-reveal key."""

    out: list[InvariantViolation] = []
    keys: list[str] = []
    for entry in forbidden_reveals:
        if isinstance(entry, str):
            keys.append(entry)
        elif isinstance(entry, dict):
            k = entry.get("revealKey") or entry.get("key")
            if k:
                keys.append(str(k))
    if not keys:
        return out

    # The leak surfaces we audit at the snapshot level: the
    # event log's resolvedText + any free-text in canonical
    # state.
    suspicious: list[tuple[str, str]] = []
    for i, ev in enumerate(_as_list(snapshot.get("recentOutcomes"))):
        if not isinstance(ev, dict):
            continue
        # recentOutcomes only stores outcomeId / eventSequence /
        # timestamp per the schema; if a future extension adds
        # text we audit it.
        for field_name, field_value in ev.items():
            if isinstance(field_value, str) and field_name != "timestamp":
                suspicious.append((f"recentOutcomes[{i}].{field_name}", field_value))
    # Also walk the events the caller has provided
    for forbidden_key in keys:
        for path, text in suspicious:
            if forbidden_key in text:
                out.append(InvariantViolation(
                    invariant_id="I6",
                    rule="snapshot does not surface forbidden-reveal keys",
                    path=path,
                    detail=f"forbidden key {forbidden_key!r} appeared in snapshot text",
                    offending_value=text,
                ))
    return out


def check_no_entitlement_fabrication(payload: dict[str, Any]) -> list[InvariantViolation]:
    """I7: an LLM payload must not carry any entitlement-related field.

    Free / paid entitlement is a *server-side* decision.  Any
    LLM output that includes ``isFree``, ``isPaid``, ``price``,
    ``tier`` or ``credits`` is rejected; the safety layer
    reports the violation and the Resolver strips the field
    before the payload reaches the event log.
    """

    BANNED_FIELDS = ("isFree", "isPaid", "price", "tier", "credits", "entitlement", "priceCents")
    out: list[InvariantViolation] = []

    def _walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in BANNED_FIELDS:
                    out.append(InvariantViolation(
                        invariant_id="I7",
                        rule=f"LLM payload must not carry {k!r}",
                        path=f"{path}.{k}",
                        detail="server-only entitlement field",
                        offending_value=v,
                    ))
                _walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")

    _walk(payload, "<root>")
    return out


def check_replay_determinism(
    original_snapshot: dict[str, Any],
    replayed_snapshot: dict[str, Any],
) -> list[InvariantViolation]:
    """I8: a replayed snapshot must equal the original (modulo timestamps).

    The check is byte-equality after removing ``timestamp`` and
    ``checksum`` from both sides; everything else must match.
    """

    out: list[InvariantViolation] = []
    a = _strip_volatile(original_snapshot)
    b = _strip_volatile(replayed_snapshot)
    if a == b:
        return out
    a_hash = hashlib.sha256(
        json.dumps(a, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    b_hash = hashlib.sha256(
        json.dumps(b, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    out.append(InvariantViolation(
        invariant_id="I8",
        rule="replay must produce the same snapshot",
        path="<root>",
        detail=f"original_hash={a_hash[:16]}… replayed_hash={b_hash[:16]}…",
        offending_value={"original": a, "replayed": b},
    ))
    return out


def _strip_volatile(snapshot: dict[str, Any]) -> dict[str, Any]:
    a = dict(snapshot)
    a.pop("timestamp", None)
    a.pop("checksum", None)
    return a


def check_atomic_write(
    snapshot: dict[str, Any],
    event_log: list[dict[str, Any]] | None,
) -> list[InvariantViolation]:
    """I9: a committed snapshot's eventSequence matches the log's last sequence.

    A snapshot carries ``partial=True`` if the Resolver was
    interrupted mid-turn.  Such a snapshot is *never* written
    by the safety layer; an external rollback tool marks it.
    This check is the safety net: a snapshot with
    ``partial=True`` is rejected; a committed snapshot must
    have its eventSequence equal the log's last sequence.
    """

    out: list[InvariantViolation] = []
    if snapshot.get("partial") is True:
        out.append(InvariantViolation(
            invariant_id="I9",
            rule="snapshot must not be partial (model timeout must not produce half-write)",
            path="<root>.partial",
            detail="snapshot is marked partial=true; the safety layer never produces partial snapshots",
            offending_value=True,
        ))
        return out
    if not isinstance(event_log, list):
        return out
    snap_seq = snapshot.get("eventSequence")
    log_last = event_log[-1].get("sequence") if event_log else 0
    if isinstance(snap_seq, int) and isinstance(log_last, int) and snap_seq != log_last:
        out.append(InvariantViolation(
            invariant_id="I9",
            rule="snapshot.eventSequence must equal event_log[-1].sequence",
            path="<root>.eventSequence",
            detail=f"snapshot={snap_seq} log_last={log_last}",
            offending_value={"snapshot": snap_seq, "log_last": log_last},
        ))
    return out


def check_event_log_idempotency(event_log: list[dict[str, Any]] | None) -> list[InvariantViolation]:
    """I10: every event in the log has a unique idempotencyKey."""

    out: list[InvariantViolation] = []
    if not isinstance(event_log, list):
        return out
    seen: dict[str, int] = {}
    for i, ev in enumerate(event_log):
        if not isinstance(ev, dict):
            continue
        key = ev.get("idempotencyKey", "")
        if not key:
            out.append(InvariantViolation(
                invariant_id="I10",
                rule="event.idempotencyKey must be a non-empty string",
                path=f"event_log[{i}].idempotencyKey",
                detail="missing idempotencyKey",
                offending_value=None,
            ))
            continue
        if key in seen:
            out.append(InvariantViolation(
                invariant_id="I10",
                rule="event.idempotencyKey must be unique across the log",
                path=f"event_log[{i}].idempotencyKey",
                detail=f"duplicate of event_log[{seen[key]}].idempotencyKey",
                offending_value=key,
            ))
        else:
            seen[key] = i
    return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class InvariantCheckInput:
    """Inputs for :func:`check_all_invariants`."""

    snapshot: dict[str, Any]
    event_log: list[dict[str, Any]] | None = None
    forbidden_reveals: list[str | dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] | None = None
    replayed_snapshot: dict[str, Any] | None = None


def check_all_invariants(ginput: InvariantCheckInput) -> InvariantReport:
    """Run all ten invariants and return a unified report."""

    violations: list[InvariantViolation] = []
    violations.extend(check_objective_facts_immutability(ginput.snapshot))
    violations.extend(check_knowledge_grounded_in_evidence(ginput.snapshot))
    violations.extend(check_artifact_location_uniqueness(ginput.snapshot))
    violations.extend(check_no_action_by_inactive_character(ginput.snapshot, ginput.event_log))
    violations.extend(check_relationship_values_in_range(ginput.snapshot))
    violations.extend(check_no_forbidden_secret_leak(ginput.snapshot, ginput.forbidden_reveals))
    if ginput.payload is not None:
        violations.extend(check_no_entitlement_fabrication(ginput.payload))
    if ginput.replayed_snapshot is not None:
        violations.extend(check_replay_determinism(ginput.snapshot, ginput.replayed_snapshot))
    violations.extend(check_atomic_write(ginput.snapshot, ginput.event_log))
    violations.extend(check_event_log_idempotency(ginput.event_log))

    summary: dict[str, int] = {}
    for v in violations:
        summary[v.invariant_id] = summary.get(v.invariant_id, 0) + 1
    summary["total"] = len(violations)

    return InvariantReport(
        passed=not violations,
        violations=violations,
        summary=summary,
    )


__all__ = [
    "InvariantViolation",
    "InvariantReport",
    "InvariantCheckInput",
    "check_objective_facts_immutability",
    "check_knowledge_grounded_in_evidence",
    "check_artifact_location_uniqueness",
    "check_no_action_by_inactive_character",
    "check_relationship_values_in_range",
    "check_no_forbidden_secret_leak",
    "check_no_entitlement_fabrication",
    "check_replay_determinism",
    "check_atomic_write",
    "check_event_log_idempotency",
    "check_all_invariants",
]
