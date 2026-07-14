"""Four-questions self-check (decision 6) — agent-side gate.

The W2-C CLI tool ``tools/four-questions-guard.py`` runs at content
submission time.  This module is the **agent-side equivalent**:
every proposal an agent emits must satisfy at least one of the
four legs before the Resolver is willing to apply it.  The check
is in-process and synchronous so it can be a hard gate inside the
agent pipeline.

Four questions (per requirements-review-v1.md §2 decision 6):

* Q1: 改变世界状态 (changes world state — artifact / event log)
* Q2: 改变人物认知 (changes character knowledge — belief matrix)
* Q3: 改变后续可用行动 (changes available actions — turn / action budget)
* Q4: 产生未来回响 (produces a future echo — causal seed / echo route)

A proposal is **valid** if at least one is true.  Returning the
set of which ones is true is the agent's audit signal.

Why duplicate the W2-C tool?
----------------------------
The W2-C tool is a **content-side** gate (does the scene contract
itself satisfy the four questions?).  This module is the
**agent-side** gate (does this particular proposal, in the
particular run / scene context, satisfy them?).  The two
complement each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


FOUR_QUESTIONS_VERSION: Final[str] = "1.0.0" if False else "1.0.0"  # always 1.0.0


@dataclass(slots=True)
class FourQuestionsResult:
    """The result of running the four-questions check.

    Attributes
    ----------
    q1_changes_world_state : bool
        True iff the proposal changes artifact ownership / state
        or appends an event-log entry.
    q2_changes_character_knowledge : bool
        True iff the proposal adds a belief update.
    q3_changes_available_actions : bool
        True iff the proposal narrows / widens the player's
        remaining actions (per scene budget or per-action count).
    q4_creates_future_echo : bool
        True iff the proposal names a causal seed in the contract
        (so the echo can fire in a future scene).
    passes : bool
        ``True`` iff at least one of Q1..Q4 is true.
    summary : list[str]
        Human-readable lines the agent / Resolver can record in
        the audit trail.
    """

    q1_changes_world_state: bool = False
    q2_changes_character_knowledge: bool = False
    q3_changes_available_actions: bool = False
    q4_creates_future_echo: bool = False
    summary: list[str] = field(default_factory=list)

    @property
    def passes(self) -> bool:
        return (
            self.q1_changes_world_state
            or self.q2_changes_character_knowledge
            or self.q3_changes_available_actions
            or self.q4_creates_future_echo
        )

    def satisfied_questions(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.q1_changes_world_state:
            out.append("Q1")
        if self.q2_changes_character_knowledge:
            out.append("Q2")
        if self.q3_changes_available_actions:
            out.append("Q3")
        if self.q4_creates_future_echo:
            out.append("Q4")
        return tuple(out)

    def to_dict(self) -> dict[str, Any]:
        return {
            "q1_changes_world_state": self.q1_changes_world_state,
            "q2_changes_character_knowledge": self.q2_changes_character_knowledge,
            "q3_changes_available_actions": self.q3_changes_available_actions,
            "q4_creates_future_echo": self.q4_creates_future_echo,
            "passes": self.passes,
            "satisfied_questions": list(self.satisfied_questions()),
            "summary": list(self.summary),
            "version": FOUR_QUESTIONS_VERSION,
        }


def check_four_questions(
    *,
    artifact_updates: Iterable[Any] = (),
    belief_updates: Iterable[Any] = (),
    budget_delta: dict[str, int] | None = None,
    fired_seed_ids: Iterable[str] = (),
    scene_mandatory_echoes: Iterable[dict[str, Any]] = (),
) -> FourQuestionsResult:
    """Run the four-questions self-check for a proposal.

    Parameters
    ----------
    artifact_updates
        Iterable of artifact update dicts; non-empty ⇒ Q1.
    belief_updates
        Iterable of belief-update dicts; non-empty ⇒ Q2.
    budget_delta
        Dict of ``action -> delta``; non-zero entries ⇒ Q3.
    fired_seed_ids
        Causal-seed IDs the proposal fires; any of them must be
        listed in the scene's mandatory_echoes for Q4 to be true
        (the agent must not invent free-form echoes).
    scene_mandatory_echoes
        The active scene's mandatory_echoes list (each entry a
        dict with at least ``id``).
    """

    result = FourQuestionsResult()

    au = list(artifact_updates)
    bu = list(belief_updates)
    seeds = list(fired_seed_ids)
    mandatory_ids = {me.get("id") for me in scene_mandatory_echoes if isinstance(me, dict)}

    if au:
        result.q1_changes_world_state = True
        result.summary.append(f"Q1: {len(au)} artifact update(s)")
    if bu:
        result.q2_changes_character_knowledge = True
        result.summary.append(f"Q2: {len(bu)} belief update(s)")
    bd = {k: int(v) for k, v in (budget_delta or {}).items() if int(v) != 0}
    if bd:
        result.q3_changes_available_actions = True
        result.summary.append(f"Q3: budget delta on {sorted(bd.keys())}")
    matched = [s for s in seeds if s in mandatory_ids]
    if matched:
        result.q4_creates_future_echo = True
        result.summary.append(f"Q4: fires mandatory echo seed(s) {matched}")
    elif seeds and not mandatory_ids:
        # The agent invented a seed the contract didn't list.
        # We treat that as **not** satisfying Q4 (decision 3 forbids
        # free-form echoes).  The Resolver will also reject the
        # proposal's fired_seed_ids that are not in the contract.
        result.summary.append(
            f"Q4: skipped (seeds={seeds} not in scene mandatory_echoes)"
        )

    if not result.passes:
        result.summary.append(
            "REJECT: proposal touches 0 of the 4 questions; would not "
            "change world state, knowledge, actions, or future echoes."
        )

    return result


def check_proposal_four_questions(
    proposal: dict[str, Any],
    *,
    scene_contract: dict[str, Any],
    budget_delta: dict[str, int] | None = None,
) -> FourQuestionsResult:
    """Convenience wrapper that reads a proposal dict and runs the check.

    The proposal is expected to be a :class:`NpcProposal` or
    :class:`DirectorBeat` in its JSON form.
    """

    artifact_updates = proposal.get("artifactUpdates", []) or []
    belief_updates = proposal.get("beliefUpdates", []) or []
    # Director beats don't carry belief updates; they fire seeds.
    fired_seeds = proposal.get("firedCausalSeeds", []) or []
    if not fired_seeds and "newCausalSeeds" in proposal:
        fired_seeds = list(proposal.get("newCausalSeeds") or [])
    return check_four_questions(
        artifact_updates=artifact_updates,
        belief_updates=belief_updates,
        budget_delta=budget_delta,
        fired_seed_ids=fired_seeds,
        scene_mandatory_echoes=scene_contract.get("mandatory_echoes", []) or [],
    )


__all__ = [
    "FOUR_QUESTIONS_VERSION",
    "FourQuestionsResult",
    "check_four_questions",
    "check_proposal_four_questions",
]
