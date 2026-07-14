"""
four_questions_guard_lib.py
===========================
Core library for the 4-Questions Self-Check (决策 6) of 《革命街没有尽头》.

The 4 questions — the behavior threshold from 决策 1:
  Q1  Does it change world state?         (artifact_updates, event_log)
  Q2  Does it change character knowledge? (belief_updates, belief_matrix)
  Q3  Does it change later available actions? (turn_budget, action_whitelist)
  Q4  Does it produce a future echo?      (causal_seeds, far_echo_routes)

Plus three mandatory additional checks (决策 6 落成清单):
  A   forbidden_reveal_risk              (扫描 forbidden_reveals 是否被违反)
  B   turn_budget_safe                   (检查 turn 数是否超出 max_turns)
  C   artifact_uniqueness                (检查 artifact 归属是否唯一)

Plus the cross-decision binding (决策 1 + 决策 3):
  D   mandatory_echo_declared            (场景合同必须显式登记 mandatory echo)
  E   npc_recall_within_mandatory        (NPC 主动提起的回响必须在 mandatory 列表里)

This module is the single source of truth for what the guard does.
The CLI wrapper in ``tools/four-questions-guard.py`` calls into it; the
content-studio backend (``tools/content-studio/``) imports it directly;
the test suite (``tests/adversarial/test_four_questions_guard.py``) covers
every branch.

Design goals
------------
* Zero required third-party dependencies beyond PyYAML (which is the
  only hard requirement for the CLI). FastAPI / uvicorn are only used
  by the optional content-studio server.
* Pure functions only — no I/O, no globals, no side effects.
* Every check returns a structured result with: id, passed (bool),
  evidence (list of strings), and detail (string).
* The aggregate ``GuardReport`` is JSON-serializable so it can be
  embedded in CI logs, content-studio UI, or replay-lab diagnostics.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - PyYAML is documented as required
    yaml = None  # type: ignore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The four core questions — order matters: this is the order the CI log
#: prints and the order the content-studio UI renders.  Do not reorder
#: without updating both consumers.
CORE_QUESTION_IDS: tuple[str, ...] = (
    "Q1_changes_world_state",
    "Q2_changes_character_knowledge",
    "Q3_changes_available_actions",
    "Q4_creates_future_echo",
)

#: The three additional checks (决策 6 必含).
ADDITIONAL_CHECK_IDS: tuple[str, ...] = (
    "A_forbidden_reveal_risk",
    "B_turn_budget_safe",
    "C_artifact_uniqueness",
)

#: The cross-decision binding checks (决策 1 + 决策 3).
MANDATORY_ECHO_CHECK_IDS: tuple[str, ...] = (
    "D_mandatory_echo_declared",
    "E_npc_recall_within_mandatory",
)

#: All check IDs in the order the guard evaluates them.  This is the
#: canonical public ordering; tests assert against it.
ALL_CHECK_IDS: tuple[str, ...] = (
    *CORE_QUESTION_IDS,
    *ADDITIONAL_CHECK_IDS,
    *MANDATORY_ECHO_CHECK_IDS,
)

#: The 12 atomic action types from PlayerAction schema — any action
#: vocabulary seen outside this set is a schema violation.
LEGAL_ACTION_TYPES: frozenset[str] = frozenset({
    "investigate",
    "reveal",
    "conceal",
    "question",
    "confront",
    "comfort",
    "give",
    "destroy",
    "promise",
    "wait",
    "leave",
    "silence",
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """One result row for a single check."""

    id: str
    label: str
    passed: bool
    evidence: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GuardReport:
    """Aggregate result of the 4-questions guard for one document."""

    document_kind: str  # "interaction" | "scene_contract" | "unknown"
    document_path: str
    blocking: bool
    blocking_reasons: list[str]
    results: list[CheckResult]
    summary: dict[str, int]  # counts of passed / failed / total

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_kind": self.document_kind,
            "document_path": self.document_path,
            "blocking": self.blocking,
            "blocking_reasons": list(self.blocking_reasons),
            "results": [r.to_dict() for r in self.results],
            "summary": dict(self.summary),
        }

    def to_human_readable(self) -> str:
        lines: list[str] = []
        verdict = "❌ BLOCK" if self.blocking else "✅ PASS"
        lines.append(f"{verdict}  {self.document_kind}  {self.document_path}")
        s = self.summary
        lines.append(
            f"summary: {s.get('passed', 0)} passed, {s.get('failed', 0)} failed, "
            f"{s.get('skipped', 0)} skipped, {s.get('total', 0)} total"
        )
        for r in self.results:
            mark = "✅" if r.passed else ("— " if r.detail.startswith("skipped") else "❌")
            lines.append(f"  {mark} [{r.id}] {r.label}")
            if r.detail:
                lines.append(f"      {r.detail}")
            for ev in r.evidence[:5]:  # cap at 5 evidence lines for readability
                lines.append(f"      · {ev}")
            if len(r.evidence) > 5:
                lines.append(f"      · … ({len(r.evidence) - 5} more)")
        if self.blocking_reasons:
            lines.append("blocking reasons:")
            for reason in self.blocking_reasons:
                lines.append(f"  - {reason}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Document loading
# ---------------------------------------------------------------------------


def _ensure_yaml() -> None:
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to load .yaml/.yml inputs. "
            "Install it with: pip install pyyaml"
        )


def load_document(path: str) -> dict[str, Any]:
    """Load a YAML or JSON file as a Python dict.

    The file extension determines the loader; ``.json`` is always parsed
    as JSON.  ``.yaml`` and ``.yml`` use PyYAML.  Anything else is
    treated as YAML (covers loose ``.txt`` content dumps).
    """
    with open(path, "r", encoding="utf-8") as fp:
        text = fp.read()
    if not text.strip():
        raise ValueError(f"document is empty: {path}")
    lower = path.lower()
    if lower.endswith(".json"):
        data = json.loads(text)
    else:
        _ensure_yaml()
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(
            f"document must deserialize to a mapping; got {type(data).__name__}: {path}"
        )
    return data


def detect_document_kind(doc: dict[str, Any]) -> str:
    """Best-effort detection of what kind of document this is.

    * ``scene_contract``  — has the ``sceneId``/``required_anchors`` shape
    * ``interaction``     — has any of the four-questions field names
    * ``unknown``         — neither
    """
    if "required_anchors" in doc and "allowed_beats" in doc:
        return "scene_contract"
    q_fields = {
        "artifact_updates",
        "event_log",
        "belief_updates",
        "belief_matrix",
        "turn_budget",
        "action_whitelist",
        "causal_seeds",
        "far_echo_routes",
    }
    if q_fields & set(doc.keys()):
        return "interaction"
    return "unknown"


# ---------------------------------------------------------------------------
# Helper predicates
# ---------------------------------------------------------------------------


def _as_list(value: Any) -> list[Any]:
    """Coerce to a list, tolerating None, scalar, or list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _nonempty(value: Any) -> bool:
    """True for non-None, non-empty, non-zero-length values."""
    if value is None:
        return False
    if isinstance(value, (list, dict, str)):
        return len(value) > 0
    return True


# ---------------------------------------------------------------------------
# The seven (4 + 3) checks
# ---------------------------------------------------------------------------


def check_q1_world_state(doc: dict[str, Any]) -> CheckResult:
    """Q1: does the interaction change world state?

    World state is captured by ``artifact_updates`` (object ownership /
    state changes) and ``event_log`` (chronicle entries).  An interaction
    is considered to change world state if **either** field contains at
    least one substantive entry.
    """
    artifact_updates = _as_list(doc.get("artifact_updates"))
    event_log = _as_list(doc.get("event_log"))

    evidence: list[str] = []
    passed = False
    detail_parts: list[str] = []

    if artifact_updates:
        passed = True
        detail_parts.append(f"artifact_updates: {len(artifact_updates)} entries")
        for upd in artifact_updates[:5]:
            if isinstance(upd, dict):
                aid = upd.get("artifactId", "?")
                owner = upd.get("newOwnerId", upd.get("ownerId", "?"))
                state = upd.get("newState", upd.get("state", "?"))
                evidence.append(f"artifact {aid} → owner={owner}, state={state}")
            else:
                evidence.append(f"artifact_updates entry: {upd!r}")
    if event_log:
        passed = True
        detail_parts.append(f"event_log: {len(event_log)} entries")
        for ev in event_log[:5]:
            if isinstance(ev, dict):
                eid = ev.get("eventId", ev.get("id", "?"))
                desc = ev.get("description", ev.get("summary", "?"))
                evidence.append(f"event {eid}: {desc}")
            else:
                evidence.append(f"event_log entry: {ev!r}")

    if not passed:
        detail = "no world-state change detected (artifact_updates & event_log both empty)"
    else:
        detail = "; ".join(detail_parts)

    return CheckResult(
        id="Q1_changes_world_state",
        label="Q1: changes world state",
        passed=passed,
        evidence=evidence,
        detail=detail,
    )


def check_q2_character_knowledge(doc: dict[str, Any]) -> CheckResult:
    """Q2: does the interaction change character knowledge?

    Character knowledge lives in ``belief_updates`` (delta to the
    cognitive map) and ``belief_matrix`` (new memories / facts that the
    character should now hold).  Either field counts.
    """
    belief_updates = _as_list(doc.get("belief_updates"))
    belief_matrix = _as_list(doc.get("belief_matrix"))

    evidence: list[str] = []
    passed = False
    detail_parts: list[str] = []

    if belief_updates:
        passed = True
        detail_parts.append(f"belief_updates: {len(belief_updates)} entries")
        for upd in belief_updates[:5]:
            if isinstance(upd, dict):
                cid = upd.get("characterId", "?")
                subj = upd.get("subject", "?")
                state = upd.get("belief_state", "?")
                conf = upd.get("confidence", "?")
                evidence.append(f"{cid}.{subj} → {state} (conf={conf})")
            else:
                evidence.append(f"belief_updates entry: {upd!r}")
    if belief_matrix:
        passed = True
        detail_parts.append(f"belief_matrix: {len(belief_matrix)} entries")
        for entry in belief_matrix[:5]:
            if isinstance(entry, dict):
                cid = entry.get("characterId", "?")
                mem = entry.get("addedMemory", entry.get("summary", "?"))
                evidence.append(f"{cid} memory: {mem}")
            else:
                evidence.append(f"belief_matrix entry: {entry!r}")

    if not passed:
        detail = "no character-knowledge change detected"
    else:
        detail = "; ".join(detail_parts)

    return CheckResult(
        id="Q2_changes_character_knowledge",
        label="Q2: changes character knowledge",
        passed=passed,
        evidence=evidence,
        detail=detail,
    )


def check_q3_available_actions(doc: dict[str, Any]) -> CheckResult:
    """Q3: does the interaction change later available actions?

    The two surfaces are ``turn_budget`` (numeric caps) and
    ``action_whitelist`` (the list of verbs still legal this scene).
    A change is recorded if **any** of the following is non-empty /
    present:

    * ``turn_budget`` (a mapping with at least one numeric cap)
    * ``turn_budget_change`` (a delta on the budget)
    * ``action_whitelist`` (explicit list, possibly shorter than before)
    * ``action_whitelist_change`` (added / removed verbs)
    """
    evidence: list[str] = []
    passed = False
    detail_parts: list[str] = []

    tb = doc.get("turn_budget")
    if isinstance(tb, dict) and tb:
        # A scene-level budget declaration is itself a change of the
        # available-action surface.
        passed = True
        detail_parts.append(f"turn_budget declared: {tb}")
        evidence.append(f"turn_budget keys: {sorted(tb.keys())}")

    tb_change = doc.get("turn_budget_change")
    if isinstance(tb_change, dict) and tb_change:
        passed = True
        detail_parts.append(f"turn_budget_change: {tb_change}")
        evidence.append(f"turn_budget delta: {tb_change}")

    aw = doc.get("action_whitelist")
    if isinstance(aw, list) and aw:
        # A list declaration narrows the universe of legal actions.
        passed = True
        verbs = [str(v) for v in aw]
        detail_parts.append(f"action_whitelist: {len(verbs)} verbs")
        # Surface any illegal verbs.
        illegal = [v for v in verbs if v not in LEGAL_ACTION_TYPES]
        if illegal:
            detail_parts.append(f"⚠ illegal verbs: {illegal}")
        evidence.append(f"action_whitelist: {verbs}")
        evidence.append(f"verb count: {len(verbs)}")

    aw_change = doc.get("action_whitelist_change")
    if isinstance(aw_change, dict) and aw_change:
        passed = True
        added = aw_change.get("added") or []
        removed = aw_change.get("removed") or []
        detail_parts.append(f"action_whitelist_change: +{added}, -{removed}")
        evidence.append(f"+{added} -{removed}")

    if not passed:
        detail = "no available-action change detected"
    else:
        detail = "; ".join(detail_parts)

    return CheckResult(
        id="Q3_changes_available_actions",
        label="Q3: changes later available actions",
        passed=passed,
        evidence=evidence,
        detail=detail,
    )


def check_q4_future_echo(doc: dict[str, Any]) -> CheckResult:
    """Q4: does the interaction produce a future echo?

    Two surfaces: ``causal_seeds`` (a new / reinforced seed) and
    ``far_echo_routes`` (a target scene that should be affected).
    Either is enough to count.
    """
    causal_seeds = _as_list(doc.get("causal_seeds"))
    far_echo_routes = _as_list(doc.get("far_echo_routes"))

    evidence: list[str] = []
    passed = False
    detail_parts: list[str] = []

    if causal_seeds:
        planted = []
        reinforced = []
        for seed in causal_seeds:
            if not isinstance(seed, dict):
                continue
            sid = seed.get("seedId", seed.get("id", "?"))
            if seed.get("planted"):
                planted.append(sid)
            else:
                reinforced.append(sid)
        if planted or reinforced:
            passed = True
            if planted:
                detail_parts.append(f"planted: {planted}")
                evidence.append(f"planted causal seeds: {planted}")
            if reinforced:
                detail_parts.append(f"reinforced: {reinforced}")
                evidence.append(f"reinforced causal seeds: {reinforced}")

    if far_echo_routes:
        passed = True
        targets = []
        for route in far_echo_routes:
            if isinstance(route, dict):
                tgt = route.get("targetSceneId") or route.get("sceneId") or "?"
                seeds = route.get("seedIds") or route.get("seed_ids") or []
                targets.append(f"{tgt}(seeds={seeds})")
            else:
                targets.append(str(route))
        detail_parts.append(f"far_echo_routes: {targets}")
        evidence.append(f"far echo routes: {targets}")

    if not passed:
        detail = "no future-echo material detected (causal_seeds & far_echo_routes both empty)"
    else:
        detail = "; ".join(detail_parts)

    return CheckResult(
        id="Q4_creates_future_echo",
        label="Q4: creates future echo",
        passed=passed,
        evidence=evidence,
        detail=detail,
    )


# --- The three additional checks (决策 6 必含) ------------------------------


def check_a_forbidden_reveal(doc: dict[str, Any]) -> CheckResult:
    """A: forbidden_reveal_risk — has any forbidden_reveals entry been
    violated by ``revealed_keys`` (or by a free-form ``utterance`` /
    ``text`` / ``narrative`` field that mentions a forbidden key)?

    The check is liberal: a forbidden ``revealKey`` appearing as a
    substring of any of the listed surface fields triggers a violation.
    """
    forbidden = _as_list(doc.get("forbidden_reveals"))
    if not forbidden:
        # No list declared — we don't synthesise one, we just report the
        # absence and move on.  The document may not even be a scene.
        return CheckResult(
            id="A_forbidden_reveal_risk",
            label="A: forbidden_reveal_risk",
            passed=True,
            evidence=[],
            detail="skipped (no forbidden_reveals declared on this document)",
        )

    forbidden_keys: list[str] = []
    for entry in forbidden:
        if isinstance(entry, dict):
            key = entry.get("revealKey") or entry.get("key")
            if key:
                forbidden_keys.append(str(key))
        elif isinstance(entry, str):
            forbidden_keys.append(entry)

    if not forbidden_keys:
        return CheckResult(
            id="A_forbidden_reveal_risk",
            label="A: forbidden_reveal_risk",
            passed=True,
            evidence=[],
            detail="skipped (forbidden_reveals declared but no revealKey values)",
        )

    # Surfaces to scan for the forbidden key.
    scan_targets: dict[str, Any] = {
        "revealed_keys": doc.get("revealed_keys"),
        "utterance": doc.get("utterance"),
        "narrative": doc.get("narrative"),
        "text": doc.get("text"),
        "dialogue": doc.get("dialogue"),
    }

    evidence: list[str] = []
    violations: list[str] = []

    for key in forbidden_keys:
        for surface_name, surface_value in scan_targets.items():
            if surface_value is None:
                continue
            if isinstance(surface_value, list):
                blob = " ".join(str(v) for v in surface_value)
            else:
                blob = str(surface_value)
            if key in blob:
                violations.append(f"{key!r} surfaced via {surface_name!r}")
                evidence.append(f"VIOLATION: {key!r} in {surface_name!r}")

    passed = len(violations) == 0
    if passed:
        detail = (
            f"scanned {len(forbidden_keys)} forbidden keys against "
            f"{sum(1 for v in scan_targets.values() if v is not None)} surfaces; no violations"
        )
    else:
        detail = f"{len(violations)} violation(s) of forbidden_reveals: {violations}"

    return CheckResult(
        id="A_forbidden_reveal_risk",
        label="A: forbidden_reveal_risk",
        passed=passed,
        evidence=evidence,
        detail=detail,
    )


def check_b_turn_budget_safe(doc: dict[str, Any]) -> CheckResult:
    """B: turn_budget_safe — is the current turn count within max_turns?

    Two input shapes are accepted:

    * ``turn_budget: { total, current_turn, max_turns, ... }``  — explicit
    * inferred from the document's own ``canonicalState.turnIndex`` /
      ``turnIndex`` and the scene's ``max_turns`` (if both present)
    """
    tb = doc.get("turn_budget")
    canonical = doc.get("canonicalState") or {}
    current_turn: int | None = None
    max_turns: int | None = None

    if isinstance(tb, dict):
        # Look in this order of preference:
        for k in ("current_turn", "turnIndex", "current"):
            if k in tb and tb[k] is not None:
                try:
                    current_turn = int(tb[k])
                    break
                except (TypeError, ValueError):
                    pass
        for k in ("max_turns", "maxTurns", "limit"):
            if k in tb and tb[k] is not None:
                try:
                    max_turns = int(tb[k])
                    break
                except (TypeError, ValueError):
                    pass

    if current_turn is None and "turnIndex" in canonical:
        try:
            current_turn = int(canonical["turnIndex"])
        except (TypeError, ValueError):
            pass
    if current_turn is None and "turnIndex" in doc:
        try:
            current_turn = int(doc["turnIndex"])
        except (TypeError, ValueError):
            pass

    if max_turns is None and "max_turns" in doc:
        try:
            max_turns = int(doc["max_turns"])
        except (TypeError, ValueError):
            pass

    if current_turn is None and max_turns is None:
        return CheckResult(
            id="B_turn_budget_safe",
            label="B: turn_budget_safe",
            passed=True,
            evidence=[],
            detail="skipped (no turn_budget / turnIndex / max_turns declared)",
        )

    if current_turn is None or max_turns is None:
        return CheckResult(
            id="B_turn_budget_safe",
            label="B: turn_budget_safe",
            passed=True,
            evidence=[],
            detail=(
                f"skipped (only one of current_turn/max_turns declared: "
                f"current_turn={current_turn}, max_turns={max_turns})"
            ),
        )

    passed = current_turn <= max_turns
    evidence = [f"current_turn={current_turn} max_turns={max_turns}"]
    if passed:
        detail = f"current_turn ({current_turn}) ≤ max_turns ({max_turns})"
    else:
        detail = (
            f"current_turn ({current_turn}) exceeds max_turns ({max_turns}) — "
            f"this interaction would blow the scene's turn budget"
        )
    return CheckResult(
        id="B_turn_budget_safe",
        label="B: turn_budget_safe",
        passed=passed,
        evidence=evidence,
        detail=detail,
    )


def check_c_artifact_uniqueness(doc: dict[str, Any]) -> CheckResult:
    """C: artifact_uniqueness — does each artifact have a unique owner?

    The check is run on whatever artifact listing the document carries
    (``artifacts`` is the preferred key, then ``artifactState``, then
    ``artifact_updates``).  If the document is a ``scene_contract`` and
    has no runtime artifact listing, the check is skipped.
    """
    artifacts: list[dict[str, Any]] = []

    raw = doc.get("artifacts")
    if isinstance(raw, list):
        artifacts = [a for a in raw if isinstance(a, dict)]
    if not artifacts:
        raw = doc.get("artifactState")
        if isinstance(raw, list):
            artifacts = [a for a in raw if isinstance(a, dict)]
    if not artifacts:
        raw = doc.get("artifact_updates")
        if isinstance(raw, list):
            artifacts = [a for a in raw if isinstance(a, dict)]

    if not artifacts:
        return CheckResult(
            id="C_artifact_uniqueness",
            label="C: artifact_uniqueness",
            passed=True,
            evidence=[],
            detail="skipped (no artifact listing on this document)",
        )

    # Bucket by artifactId, collect all distinct owners.
    by_id: dict[str, set[str]] = {}
    for art in artifacts:
        aid = str(art.get("artifactId") or art.get("id") or "?")
        owner = art.get("ownerId") or art.get("newOwnerId") or "<unknown>"
        by_id.setdefault(aid, set()).add(str(owner))

    evidence: list[str] = []
    duplicates: list[str] = []
    for aid, owners in sorted(by_id.items()):
        if len(owners) > 1:
            duplicates.append(f"{aid}={sorted(owners)}")
            evidence.append(f"DUPLICATE: {aid} claimed by {sorted(owners)}")
        else:
            evidence.append(f"{aid} → {next(iter(owners))}")

    passed = len(duplicates) == 0
    if passed:
        detail = f"all {len(by_id)} artifact(s) have a unique owner"
    else:
        detail = f"{len(duplicates)} artifact(s) have multiple owners: {duplicates}"

    return CheckResult(
        id="C_artifact_uniqueness",
        label="C: artifact_uniqueness",
        passed=passed,
        evidence=evidence,
        detail=detail,
    )


# --- The cross-decision binding checks (决策 1 + 决策 3) -------------------


def check_d_mandatory_echo_declared(doc: dict[str, Any]) -> CheckResult:
    """D: a scene_contract must explicitly declare its mandatory echo list
    (决策 3).  An interaction document is exempt from this check.
    """
    kind = detect_document_kind(doc)
    if kind != "scene_contract":
        return CheckResult(
            id="D_mandatory_echo_declared",
            label="D: mandatory_echo_declared",
            passed=True,
            evidence=[],
            detail=f"skipped (document kind is {kind!r}, not scene_contract)",
        )

    mandatory = doc.get("mandatory_echoes")
    if not isinstance(mandatory, list) or not mandatory:
        return CheckResult(
            id="D_mandatory_echo_declared",
            label="D: mandatory_echo_declared",
            passed=False,
            evidence=[],
            detail=(
                "scene_contract is missing a non-empty `mandatory_echoes` list — "
                "决策 3 requires every scene to explicitly declare its mandatory echo list"
            ),
        )

    evidence: list[str] = []
    for echo in mandatory:
        if isinstance(echo, dict):
            eid = echo.get("id") or echo.get("seedId") or "?"
            desc = echo.get("description", "")
            evidence.append(f"mandatory: {eid} — {desc}")
        else:
            evidence.append(f"mandatory: {echo!r}")

    return CheckResult(
        id="D_mandatory_echo_declared",
        label="D: mandatory_echo_declared",
        passed=True,
        evidence=evidence,
        detail=f"{len(mandatory)} mandatory echo(es) declared",
    )


def check_e_npc_recall_within_mandatory(doc: dict[str, Any]) -> CheckResult:
    """E: every NPC-raised echo in an interaction must appear in the
    document's mandatory_echoes list (or, if the document is a contract,
    in that contract's mandatory list).

    Without this, the AI Director is free to invent echoes on the fly —
    exactly what 决策 3 forbids ("AI 导演不能自由发挥").
    """
    npc_raised = _as_list(doc.get("npc_raised_echoes"))
    if not npc_raised:
        return CheckResult(
            id="E_npc_recall_within_mandatory",
            label="E: npc_recall_within_mandatory",
            passed=True,
            evidence=[],
            detail="skipped (no npc_raised_echoes in this document)",
        )

    # Two sources of "mandatory" — explicit list on this document, or
    # the parent contract referenced by ``sceneId`` if it can be found
    # alongside the document on disk.  For the CLI / API surface we do
    # not chase references; the document is expected to carry either
    # ``mandatory_echoes`` or ``inherited_mandatory_echoes``.
    mandatory_ids: set[str] = set()
    for source in (doc.get("mandatory_echoes"), doc.get("inherited_mandatory_echoes")):
        for entry in _as_list(source):
            if isinstance(entry, dict):
                eid = entry.get("id") or entry.get("seedId")
                if eid:
                    mandatory_ids.add(str(eid))
            elif entry is not None:
                mandatory_ids.add(str(entry))

    evidence: list[str] = []
    violations: list[str] = []
    for echo in npc_raised:
        if not isinstance(echo, dict):
            continue
        eid = str(echo.get("id") or echo.get("seedId") or "?")
        speaker = echo.get("speaker", "?")
        line = echo.get("line", "")
        in_list = bool(echo.get("inMandatoryList", eid in mandatory_ids))
        marker = "✓" if in_list else "✗"
        evidence.append(f"{marker} NPC {speaker} raised {eid!r}: {line} (inMandatory={in_list})")
        if not in_list:
            violations.append(f"{eid} raised by {speaker}")

    # If neither in-document mandatory list nor explicit inMandatoryList
    # flags were supplied, the check is *indeterminate* (skipped).
    has_anchors = bool(mandatory_ids) or any(
        isinstance(e, dict) and "inMandatoryList" in e for e in npc_raised
    )
    if not has_anchors:
        return CheckResult(
            id="E_npc_recall_within_mandatory",
            label="E: npc_recall_within_mandatory",
            passed=True,
            evidence=evidence,
            detail=(
                "skipped (no mandatory_echoes list supplied for cross-check; "
                "guard cannot verify NPC-raised echoes against the scene's contract)"
            ),
        )

    passed = len(violations) == 0
    if passed:
        detail = f"all {len(npc_raised)} NPC-raised echo(es) are within the mandatory list"
    else:
        detail = (
            f"{len(violations)} NPC-raised echo(es) are NOT in the mandatory list — "
            f"AI 导演 must not invent echoes: {violations}"
        )
    return CheckResult(
        id="E_npc_recall_within_mandatory",
        label="E: npc_recall_within_mandatory",
        passed=passed,
        evidence=evidence,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# The orchestrator
# ---------------------------------------------------------------------------


def _is_blocking(kind: str, check_id: str, result: CheckResult) -> bool:
    """Centralised blocking policy.

    The blocking policy differs by document kind:

    * **scene_contract** — Q1/Q2/Q4 are *advisory* (a contract is a
      declaration, not a runtime event; those runtime fields will be
      filled in by the Resolver).  **D** is the only hard block on a
      contract (决策 3: mandatory echo list MUST be declared before
      merge).  **A** is blocking when forbidden_reveals is declared
      and the contract fails to scan the surface (we keep this
      advisory: a contract that fails the scan means the scene has
      no surface to leak through, which is a design choice rather
      than a violation — but we surface it).
    * **interaction** — all 9 checks are blocking (决策 1: A 触达 +
      B 因果; 决策 3: NPC 不能自由发挥; 决策 6: 全部附加检查).
    * **unknown** — only D and A are blocking; the rest are advisory
      because we cannot prove the document is runtime-typed.
    """
    if result.passed or result.detail.startswith("skipped"):
        return False
    if check_id in {"D_mandatory_echo_declared"}:
        # D is always blocking — a missing mandatory echo list is
        # decision-3 P0.
        return True
    if check_id == "A_forbidden_reveal_risk":
        # Only blocking on scenes/interactions: an "unknown" document
        # is allowed to skip A.  A scene/interaction that scans
        # forbidden_reveals and finds a violation is blocking.
        return kind in {"scene_contract", "interaction"}
    if kind == "scene_contract":
        # Q1-Q4, B, C, E are advisory on scene contracts.
        return False
    # interaction (or unknown) — full blocking policy.
    return True


def run_guard(
    doc: dict[str, Any],
    document_path: str = "<memory>",
    *,
    check_ids: Iterable[str] | None = None,
) -> GuardReport:
    """Run the full 4-questions guard against one document.

    Parameters
    ----------
    doc:
        The parsed document (YAML / JSON mapping).
    document_path:
        Used only for the report header.  ``"<memory>"`` if the caller
        is constructing an in-memory test fixture.
    check_ids:
        Optional whitelist of check IDs to evaluate.  When omitted
        (the default), all 9 checks run.
    """
    check_factories = {
        "Q1_changes_world_state": check_q1_world_state,
        "Q2_changes_character_knowledge": check_q2_character_knowledge,
        "Q3_changes_available_actions": check_q3_available_actions,
        "Q4_creates_future_echo": check_q4_future_echo,
        "A_forbidden_reveal_risk": check_a_forbidden_reveal,
        "B_turn_budget_safe": check_b_turn_budget_safe,
        "C_artifact_uniqueness": check_c_artifact_uniqueness,
        "D_mandatory_echo_declared": check_d_mandatory_echo_declared,
        "E_npc_recall_within_mandatory": check_e_npc_recall_within_mandatory,
    }
    selected = tuple(check_ids) if check_ids is not None else ALL_CHECK_IDS
    unknown = [c for c in selected if c not in check_factories]
    if unknown:
        raise ValueError(f"unknown check ids: {unknown}")

    kind = detect_document_kind(doc)
    results: list[CheckResult] = []
    for cid in selected:
        results.append(check_factories[cid](doc))

    # --- Blocking policy --------------------------------------------------
    blocking_reasons: list[str] = []
    for r in results:
        if _is_blocking(kind, r.id, r):
            blocking_reasons.append(f"{r.id}: {r.detail}")

    # --- Summary ---------------------------------------------------------
    passed = sum(1 for r in results if r.passed and not r.detail.startswith("skipped"))
    failed = sum(1 for r in results if not r.passed and not r.detail.startswith("skipped"))
    skipped = sum(1 for r in results if r.detail.startswith("skipped"))
    summary = {"passed": passed, "failed": failed, "skipped": skipped, "total": len(results)}

    return GuardReport(
        document_kind=kind,
        document_path=document_path,
        blocking=bool(blocking_reasons),
        blocking_reasons=blocking_reasons,
        results=results,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "ALL_CHECK_IDS",
    "CORE_QUESTION_IDS",
    "ADDITIONAL_CHECK_IDS",
    "MANDATORY_ECHO_CHECK_IDS",
    "LEGAL_ACTION_TYPES",
    "CheckResult",
    "GuardReport",
    "check_q1_world_state",
    "check_q2_character_knowledge",
    "check_q3_available_actions",
    "check_q4_future_echo",
    "check_a_forbidden_reveal",
    "check_b_turn_budget_safe",
    "check_c_artifact_uniqueness",
    "check_d_mandatory_echo_declared",
    "check_e_npc_recall_within_mandatory",
    "detect_document_kind",
    "load_document",
    "run_guard",
    "_is_blocking",
]
