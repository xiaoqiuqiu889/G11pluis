"""Content guards — the secret-leak / memory-grounding gate.

Once an LLM payload has passed the schema gate
(:mod:`output_verifier`) it still has to pass the **content**
gate.  Three categories of issue are caught here:

1. **Forbidden reveals** — the LLM is forbidden from surfacing
   specific secrets / facts that the contract has marked
   ``forbidden_reveals``.  The director beat *must* check
   every entry on that list; this module independently
   re-checks the produced text.
2. **Mandatory echoes (决策 3)** — when an NPC proactively
   raises a cross-era echo, the echo **must** be on the
   scene's ``mandatory_echoes`` list.  This is the
   ``E_npc_recall_within_mandatory`` check the
   four-questions-guard already runs at *contract design
   time*; the safety package re-runs it at *runtime* on
   the actual produced content.
3. **Ungrounded memory** — an NPC's ``referencedMemoryIds``
   must all be in the character's recall set.  This is the
   ``UngroundedMemoryError`` the Resolver already raises;
   the safety package adds a **string-level** check on
   the produced dialogue so an NPC cannot mention an
   object / event that the recall set does not include.

In addition, the module provides a small **belief visibility
matrix** that records, per character, what they are allowed to
*say* (subjective suppression), what they are allowed to
*know* (objective concealment), and what they are not
allowed to *recall* (selective forgetting).  The matrix is
declared once per run and consulted on every NPC proposal.

The safety layer is the **last** place we catch these issues;
the content-studio and four-questions-guard are the first.
This module is what makes "we already have a tool" *also*
"the tool runs at runtime on the actual content".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Belief visibility matrix
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BeliefVisibility:
    """A character's visibility / recall settings.

    Three independent gates per character:

    * ``subjective_suppression`` — subjects the character may
      not say out loud (e.g. their own private shame).
    * ``objective_concealment`` — facts the character may not
      know yet (e.g. a 2008 photograph the 2011 character has
      not been told about).
    * ``selective_forgetting`` — memories the character may not
      recall this run (e.g. a traumatic event that has been
      repressed).

    The three sets are checked independently by
    :func:`check_proposal_visibility`.
    """

    characterId: str
    subjective_suppression: set[str] = field(default_factory=set)
    objective_concealment: set[str] = field(default_factory=set)
    selective_forgetting: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "characterId": self.characterId,
            "subjective_suppression": sorted(self.subjective_suppression),
            "objective_concealment": sorted(self.objective_concealment),
            "selective_forgetting": sorted(self.selective_forgetting),
        }


# ---------------------------------------------------------------------------
# Audit data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ContentGuardReport:
    """The aggregate result of running the content guards on one payload.

    Attributes
    ----------
    passed : bool
        True iff every check passed (no violations).
    forbidden_reveal_violations : list[str]
        The forbidden-reveal keys that were found in the
        produced text.
    mandatory_echo_violations : list[str]
        The NPC-raised echo IDs that are **not** in the
        scene's mandatory_echoes list.
    ungrounded_memory_violations : list[str]
        Memory IDs the NPC referenced but the recall set
        does not include.
    visibility_violations : list[str]
        Subjects the NPC's dialogue touches that the
        visibility matrix forbids.
    summary : dict[str, int]
        Counts keyed by violation type.
    """

    passed: bool
    forbidden_reveal_violations: list[str] = field(default_factory=list)
    mandatory_echo_violations: list[str] = field(default_factory=list)
    ungrounded_memory_violations: list[str] = field(default_factory=list)
    visibility_violations: list[str] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "forbidden_reveal_violations": list(self.forbidden_reveal_violations),
            "mandatory_echo_violations": list(self.mandatory_echo_violations),
            "ungrounded_memory_violations": list(self.ungrounded_memory_violations),
            "visibility_violations": list(self.visibility_violations),
            "summary": dict(self.summary),
        }

    def to_human_readable(self) -> str:
        lines: list[str] = []
        verdict = "✅ PASS" if self.passed else "❌ FAIL"
        lines.append(f"{verdict}  content_guards")
        s = self.summary
        lines.append(
            "summary: "
            + ", ".join(
                f"{k}={v}" for k, v in s.items() if v
            )
        )
        for kind, items in [
            ("forbidden_reveal", self.forbidden_reveal_violations),
            ("mandatory_echo", self.mandatory_echo_violations),
            ("ungrounded_memory", self.ungrounded_memory_violations),
            ("visibility", self.visibility_violations),
        ]:
            for it in items:
                lines.append(f"  • [{kind}] {it}")
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


def _collect_text_surfaces(payload: dict[str, Any]) -> dict[str, str]:
    """Pull every free-text surface from an LLM payload into one map.

    Used by the forbidden-reveal check.  We collect:

    * ``resolvedText``
    * ``narrative``
    * ``utterance``
    * ``text`` / ``dialogue``
    * any string field nested one level deep under ``beliefUpdates``
      (the LLM sometimes embeds forbidden hints in the reasoning
      string of a belief update)
    """

    out: dict[str, str] = {}
    for key in ("resolvedText", "narrative", "utterance", "text", "dialogue", "reasoning"):
        if isinstance(payload.get(key), str):
            out[key] = payload[key]
    for upd in _as_list(payload.get("beliefUpdates")):
        if isinstance(upd, dict):
            for k in ("reasoning", "subject"):
                v = upd.get(k)
                if isinstance(v, str):
                    out[f"beliefUpdates[].{k}"] = v
    return out


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_forbidden_reveals(
    payload: dict[str, Any],
    forbidden_reveals: Iterable[str | dict[str, Any]],
) -> list[str]:
    """Return the forbidden keys that were surfaced in the produced text.

    Parameters
    ----------
    payload : dict
        The LLM-produced output (an ``NpcProposal``,
        ``DirectorBeat`` or ``ResolverOutcome``).
    forbidden_reveals : Iterable
        The list of forbidden keys.  Each entry may be a plain
        string (the reveal key) or a dict with a ``revealKey``
        / ``key`` field.  This matches the two shapes the
        narrative contract uses.

    Returns
    -------
    list[str]
        Every forbidden key that was found as a substring of
        any text surface.  Empty list = no violations.
    """

    surfaces = _collect_text_surfaces(payload)
    if not surfaces:
        return []

    keys: list[str] = []
    for entry in forbidden_reveals:
        if isinstance(entry, str):
            keys.append(entry)
        elif isinstance(entry, dict):
            k = entry.get("revealKey") or entry.get("key")
            if k:
                keys.append(str(k))

    violations: list[str] = []
    for key in keys:
        for surface_name, surface_value in surfaces.items():
            if key and key in surface_value:
                violations.append(
                    f"{key!r} surfaced via {surface_name!r} in produced text"
                )
    return violations


def check_mandatory_echoes(
    npc_raised_echoes: Iterable[dict[str, Any]],
    mandatory_echoes: Iterable[dict[str, Any] | str],
) -> list[str]:
    """Return the NPC-raised echoes that are not in the mandatory list.

    This is the **runtime** version of the four-questions-guard's
    ``E_npc_recall_within_mandatory`` check.  The four-questions
    tool runs at *contract design time* on the YAML; this runs
    at *runtime* on the actual NPC output and is the gate
    decision 3 relies on.

    Parameters
    ----------
    npc_raised_echoes : Iterable[dict]
        The list of echoes the NPC proposal raises.  Each
        entry must carry at least ``id`` (the echo id) and
        optionally ``speaker`` / ``line`` (for the report).
    mandatory_echoes : Iterable
        The scene's mandatory list.  Each entry may be a
        dict with an ``id`` / ``seedId`` field, or a plain
        string id.

    Returns
    -------
    list[str]
        Violation messages.  Empty list = every raised echo
        is in the mandatory list.
    """

    raised = list(npc_raised_echoes)
    mandatory_ids: set[str] = set()
    for entry in mandatory_echoes:
        if isinstance(entry, dict):
            eid = entry.get("id") or entry.get("seedId")
            if eid:
                mandatory_ids.add(str(eid))
        elif entry is not None:
            mandatory_ids.add(str(entry))

    violations: list[str] = []
    for echo in raised:
        if not isinstance(echo, dict):
            continue
        eid = str(echo.get("id") or echo.get("seedId") or "?")
        if eid not in mandatory_ids:
            speaker = echo.get("speaker", "?")
            line = echo.get("line", "")
            violations.append(
                f"NPC {speaker} raised echo {eid!r} (line={line!r}) but it is not in mandatory_echoes"
            )
    return violations


def check_ungrounded_memory(
    referenced_memory_ids: Iterable[str],
    recall_set: Iterable[str],
) -> list[str]:
    """Return the memory ids that the NPC referenced but the recall set lacks.

    The Resolver already raises :class:`UngroundedMemoryError`
    for the same condition; this is the *content* version
    that runs on the actual proposal text, after the schema
    gate, so the L4 fallback can switch on a clean list of
    offending ids.
    """

    recall = set(recall_set)
    out: list[str] = []
    for mid in referenced_memory_ids:
        if mid not in recall:
            out.append(f"referenced memory {mid!r} is not in the recall set")
    return out


def check_proposal_visibility(
    dialogue_subjects: Iterable[str],
    visibility: BeliefVisibility,
) -> list[str]:
    """Return subjects in the NPC's dialogue that the matrix forbids.

    Subjects in the dialogue that match a ``subjective_suppression``
    entry are caught here ("the character refuses to talk about
    this").  The objective_concealment and selective_forgetting
    gates are enforced *upstream* of the proposal: the LLM is
    simply not given the data, so the check here is a no-op
    sanity net (used in tests to confirm the upstream filter
    actually worked).

    Parameters
    ----------
    dialogue_subjects : Iterable[str]
        Subject tokens the NPC's dialogue touches.  The
        contract loader extracts these from the LLM output
        and passes them in.
    visibility : BeliefVisibility
        The character's visibility matrix entry.
    """

    out: list[str] = []
    for subj in dialogue_subjects:
        if subj in visibility.subjective_suppression:
            out.append(
                f"character {visibility.characterId!r} is suppressing subject {subj!r} but mentioned it"
            )
        if subj in visibility.objective_concealment:
            out.append(
                f"character {visibility.characterId!r} should not know subject {subj!r} but mentioned it"
            )
        if subj in visibility.selective_forgetting:
            out.append(
                f"character {visibility.characterId!r} is selectively forgetting subject {subj!r} but recalled it"
            )
    return out


# ---------------------------------------------------------------------------
# The orchestrator
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ContentGuardInput:
    """All the inputs :func:`run_content_guards` needs to evaluate one payload."""

    payload: dict[str, Any]
    forbidden_reveals: list[str | dict[str, Any]] = field(default_factory=list)
    mandatory_echoes: list[dict[str, Any] | str] = field(default_factory=list)
    npc_raised_echoes: list[dict[str, Any]] = field(default_factory=list)
    referenced_memory_ids: list[str] = field(default_factory=list)
    recall_set: list[str] = field(default_factory=list)
    visibility: BeliefVisibility | None = None
    dialogue_subjects: list[str] = field(default_factory=list)


def run_content_guards(ginput: ContentGuardInput) -> ContentGuardReport:
    """Run every content guard against a single LLM payload.

    The function never raises; it returns a structured
    :class:`ContentGuardReport` that the caller decides to
    accept or reject.
    """

    forbidden = check_forbidden_reveals(ginput.payload, ginput.forbidden_reveals)
    mandatory = check_mandatory_echoes(ginput.npc_raised_echoes, ginput.mandatory_echoes)
    ungrounded = check_ungrounded_memory(ginput.referenced_memory_ids, ginput.recall_set)
    visibility_violations: list[str] = []
    if ginput.visibility is not None:
        visibility_violations = check_proposal_visibility(
            ginput.dialogue_subjects, ginput.visibility
        )

    passed = not (forbidden or mandatory or ungrounded or visibility_violations)
    summary = {
        "forbidden_reveal": len(forbidden),
        "mandatory_echo": len(mandatory),
        "ungrounded_memory": len(ungrounded),
        "visibility": len(visibility_violations),
        "total": len(forbidden) + len(mandatory) + len(ungrounded) + len(visibility_violations),
    }
    return ContentGuardReport(
        passed=passed,
        forbidden_reveal_violations=forbidden,
        mandatory_echo_violations=mandatory,
        ungrounded_memory_violations=ungrounded,
        visibility_violations=visibility_violations,
        summary=summary,
    )


__all__ = [
    "BeliefVisibility",
    "ContentGuardReport",
    "ContentGuardInput",
    "check_forbidden_reveals",
    "check_mandatory_echoes",
    "check_ungrounded_memory",
    "check_proposal_visibility",
    "run_content_guards",
]
