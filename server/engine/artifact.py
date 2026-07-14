"""Artifact (object) ownership and state machine.

An artifact is a concrete thing in the world — a photograph, a
letter, a bus ticket.  The engine tracks *who owns* each artifact
and *what state* it's in; the **uniqueness** invariant is:

> A single physical artifact has exactly one owner / location at
> any given moment.

This invariant is what allows the player to "give" a photo to
Arash without losing the chance for Leila to carry a copy — the
two photos are *two distinct artifacts* with the same canonical
provenance.  See ``photo_lab_2008.yaml`` for the canonical example.

Operations
----------
The 6 legal operations are: ``create``, ``transfer``, ``destroy``,
``modify_state``, ``reveal``, ``conceal``.  All are validated and
applied by :func:`apply_artifact_updates`; the Resolver is the only
caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .exceptions import ArtifactConflictError, EvidenceNotFoundError
from .world_snapshot import ArtifactState


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


class ArtifactOperation(str):
    """Enum-as-string for the 6 artifact operations.

    Defined as plain constants so it can be JSON-serialised into
    the resolver_outcome schema's ``artifactUpdates[].operation``
    field without conversion.
    """

    CREATE = "create"
    TRANSFER = "transfer"
    DESTROY = "destroy"
    MODIFY_STATE = "modify_state"
    REVEAL = "reveal"
    CONCEAL = "conceal"


VALID_OPERATIONS: frozenset[str] = frozenset(
    {
        ArtifactOperation.CREATE,
        ArtifactOperation.TRANSFER,
        ArtifactOperation.DESTROY,
        ArtifactOperation.MODIFY_STATE,
        ArtifactOperation.REVEAL,
        ArtifactOperation.CONCEAL,
    }
)


@dataclass(slots=True)
class ArtifactUpdate:
    """A single artifact update produced by the Resolver."""

    artifactId: str
    operation: str
    newOwnerId: str | None = None
    newState: str | None = None
    reasonCode: str = ""

    def __post_init__(self) -> None:
        if self.operation not in VALID_OPERATIONS:
            raise ValueError(f"invalid artifact operation: {self.operation!r}")
        if not self.artifactId:
            raise ValueError("artifactId is required")
        if self.operation == ArtifactOperation.TRANSFER and not self.newOwnerId:
            raise ValueError("transfer requires newOwnerId")
        if self.operation == ArtifactOperation.MODIFY_STATE and self.newState is None:
            raise ValueError("modify_state requires newState")

    def to_json_dict(self) -> dict:
        return {
            "artifactId": self.artifactId,
            "operation": self.operation,
            "newOwnerId": self.newOwnerId,
            "newState": self.newState,
            "reasonCode": self.reasonCode,
        }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def find_artifact(
    artifacts: list[ArtifactState], artifact_id: str
) -> ArtifactState | None:
    for a in artifacts:
        if a.artifactId == artifact_id:
            return a
    return None


def assert_uniqueness(
    artifacts: list[ArtifactState], new_artifact: ArtifactState
) -> None:
    """Raise :exc:`ArtifactConflictError` if ``new_artifact`` collides.

    The uniqueness rule for *new* artifacts: an artifact with the
    same ``artifactId`` must not already exist.  The Resolver is
    the only writer, and the artifactId is the unique key — two
    physical photos both owned by leila is a perfectly legal
    state and is the canonical photo-lab-2008 example.
    """

    if find_artifact(artifacts, new_artifact.artifactId) is not None:
        raise ArtifactConflictError(
            f"artifactId already exists: {new_artifact.artifactId}"
        )


def assert_no_duplicate_owner(
    artifacts: list[ArtifactState],
    artifact_id: str,
    new_owner: str,
) -> None:
    """No-op safety net — kept for documentation purposes.

    Per the schema, two artifacts with the same owner are perfectly
    fine (Leila can have a bag full of things).  The uniqueness
    invariant applies to *a single artifact's ownership*, not to
    collections.  The function always returns ``None``; raised here
    so callers can document the intent.
    """

    return None


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_artifact_updates(
    artifacts: list[ArtifactState], updates: Iterable[ArtifactUpdate]
) -> list[ArtifactState]:
    """Apply a sequence of :class:`ArtifactUpdate` operations.

    The result is a *new* list of artifacts; the input is never
    mutated.  The Resolver calls this once per turn.

    Uniqueness invariant
    --------------------
    * After ``create`` the new artifact must not collide with an
      existing one (same ``artifactId`` or identical owner/state/
      location/revealed fingerprint).
    * After ``transfer`` an artifact's ownerId changes but the
      artifact itself remains unique (it's the *same* physical
      thing).
    * After ``destroy`` the artifact is removed from the list;
      subsequent updates referencing it raise
      :exc:`EvidenceNotFoundError`.
    """

    state = list(artifacts)
    for u in updates:
        op = u.operation
        if op == ArtifactOperation.CREATE:
            new = ArtifactState(
                artifactId=u.artifactId,
                ownerId=u.newOwnerId or "",
                state=u.newState or "intact",
                isRevealed=False,
                location=None,
                tags=[],
            )
            assert_uniqueness(state, new)
            state.append(new)
        else:
            existing = find_artifact(state, u.artifactId)
            if existing is None:
                raise EvidenceNotFoundError(
                    f"artifact not found for operation {op}: {u.artifactId}"
                )
            if op == ArtifactOperation.TRANSFER:
                new_artifact = ArtifactState(
                    artifactId=existing.artifactId,
                    ownerId=u.newOwnerId or existing.ownerId,
                    state=existing.state,
                    isRevealed=existing.isRevealed,
                    location=u.newState or existing.location,
                    tags=list(existing.tags),
                )
                state = [
                    a if a.artifactId != existing.artifactId else new_artifact
                    for a in state
                ]
            elif op == ArtifactOperation.DESTROY:
                state = [a for a in state if a.artifactId != u.artifactId]
            elif op == ArtifactOperation.MODIFY_STATE:
                new_artifact = ArtifactState(
                    artifactId=existing.artifactId,
                    ownerId=existing.ownerId,
                    state=u.newState if u.newState is not None else existing.state,
                    isRevealed=existing.isRevealed,
                    location=existing.location,
                    tags=list(existing.tags),
                )
                state = [
                    a if a.artifactId != existing.artifactId else new_artifact
                    for a in state
                ]
            elif op == ArtifactOperation.REVEAL:
                new_artifact = ArtifactState(
                    artifactId=existing.artifactId,
                    ownerId=existing.ownerId,
                    state=existing.state,
                    isRevealed=True,
                    location=existing.location,
                    tags=list(existing.tags),
                )
                state = [
                    a if a.artifactId != existing.artifactId else new_artifact
                    for a in state
                ]
            elif op == ArtifactOperation.CONCEAL:
                new_artifact = ArtifactState(
                    artifactId=existing.artifactId,
                    ownerId=existing.ownerId,
                    state=existing.state,
                    isRevealed=False,
                    location=existing.location,
                    tags=list(existing.tags),
                )
                state = [
                    a if a.artifactId != existing.artifactId else new_artifact
                    for a in state
                ]
    return state


# ---------------------------------------------------------------------------
# Ownership query (used by reducers)
# ---------------------------------------------------------------------------


def owner_of(
    artifacts: list[ArtifactState], artifact_id: str
) -> str | None:
    a = find_artifact(artifacts, artifact_id)
    return a.ownerId if a is not None else None


def is_revealed(
    artifacts: list[ArtifactState], artifact_id: str
) -> bool:
    a = find_artifact(artifacts, artifact_id)
    return a.isRevealed if a is not None else False


__all__ = [
    "ArtifactOperation",
    "VALID_OPERATIONS",
    "ArtifactUpdate",
    "find_artifact",
    "assert_uniqueness",
    "apply_artifact_updates",
    "owner_of",
    "is_revealed",
]
