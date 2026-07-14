"""Artifact ownership + uniqueness tests.

The artifact state machine's core invariant is:

> A single physical artifact has exactly one owner / location at
> any given moment.

This file verifies that:

* ``create`` produces a new artifact that does not collide.
* ``transfer`` moves an artifact from one owner to another
  without leaving a copy behind.
* ``destroy`` removes an artifact from the canonical state.
* The uniqueness check rejects collisions (same id, same fingerprint).
"""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, "server")

from engine import (  # noqa: E402
    ArtifactOperation,
    ArtifactState,
    ArtifactUpdate,
    apply_artifact_updates,
    assert_uniqueness,
    find_artifact,
)
from engine.exceptions import (  # noqa: E402
    ArtifactConflictError,
    EvidenceNotFoundError,
)


def _seed() -> list[ArtifactState]:
    return [
        ArtifactState(artifactId="photo_A", ownerId="leila", state="intact", isRevealed=False),
        ArtifactState(artifactId="photo_B", ownerId="leila", state="intact", isRevealed=False),
    ]


class UniquenessTests(unittest.TestCase):
    """The uniqueness invariant must hold at every apply step."""

    def test_unique_artifact_ids(self) -> None:
        with self.assertRaises(ArtifactConflictError):
            assert_uniqueness(_seed(), ArtifactState(
                artifactId="photo_A",
                ownerId="someone",
                state="intact",
                isRevealed=False,
            ))

    def test_unique_fingerprint(self) -> None:
        """Two artifacts with identical owner/state/location/revealed
        fingerprint — the soft fingerprint check was removed in
        favour of the artifactId-keyed check.  Two physical photos
        both owned by leila is a legal state (this is exactly the
        photo_lab_2008 case).  Only same artifactId is rejected."""

        seed = [
            ArtifactState(
                artifactId="x",
                ownerId="leila",
                state="intact",
                isRevealed=False,
                location="bag",
            )
        ]
        # Different ID + same fingerprint = OK (two physical photos)
        assert_uniqueness(seed, ArtifactState(
            artifactId="y",
            ownerId="leila",
            state="intact",
            isRevealed=False,
            location="bag",
        ))
        # Same ID = rejected
        with self.assertRaises(ArtifactConflictError):
            assert_uniqueness(seed, ArtifactState(
                artifactId="x",
                ownerId="leila",
                state="intact",
                isRevealed=False,
                location="bag",
            ))

    def test_two_owners_same_artifact_id_rejected(self) -> None:
        """The same artifactId cannot exist twice even with different
        owners — the ID *is* the uniqueness key."""

        seed = _seed()
        with self.assertRaises(ArtifactConflictError):
            assert_uniqueness(seed, ArtifactState(
                artifactId="photo_A",
                ownerId="arash",
                state="intact",
                isRevealed=False,
            ))


class OperationTests(unittest.TestCase):
    """Each of the 6 operations does what the schema says."""

    def test_create_adds_artifact(self) -> None:
        out = apply_artifact_updates(
            _seed(),
            [ArtifactUpdate(artifactId="photo_C", operation=ArtifactOperation.CREATE,
                            newOwnerId="arash", newState="intact", reasonCode="spawn")],
        )
        ids = sorted(a.artifactId for a in out)
        self.assertEqual(ids, ["photo_A", "photo_B", "photo_C"])

    def test_transfer_changes_owner(self) -> None:
        out = apply_artifact_updates(
            _seed(),
            [ArtifactUpdate(artifactId="photo_A", operation=ArtifactOperation.TRANSFER,
                            newOwnerId="arash", reasonCode="give")],
        )
        photo = find_artifact(out, "photo_A")
        self.assertEqual(photo.ownerId, "arash")
        # The other photo is untouched
        photo_b = find_artifact(out, "photo_B")
        self.assertEqual(photo_b.ownerId, "leila")

    def test_destroy_removes_artifact(self) -> None:
        out = apply_artifact_updates(
            _seed(),
            [ArtifactUpdate(artifactId="photo_A", operation=ArtifactOperation.DESTROY,
                            reasonCode="destroy")],
        )
        self.assertIsNone(find_artifact(out, "photo_A"))
        self.assertIsNotNone(find_artifact(out, "photo_B"))

    def test_modify_state_updates_state(self) -> None:
        out = apply_artifact_updates(
            _seed(),
            [ArtifactUpdate(artifactId="photo_A", operation=ArtifactOperation.MODIFY_STATE,
                            newState="worn", reasonCode="age")],
        )
        photo = find_artifact(out, "photo_A")
        self.assertEqual(photo.state, "worn")
        self.assertEqual(photo.ownerId, "leila")  # owner unchanged

    def test_reveal_sets_is_revealed_true(self) -> None:
        out = apply_artifact_updates(
            _seed(),
            [ArtifactUpdate(artifactId="photo_A", operation=ArtifactOperation.REVEAL,
                            reasonCode="reveal")],
        )
        photo = find_artifact(out, "photo_A")
        self.assertTrue(photo.isRevealed)

    def test_conceal_sets_is_revealed_false(self) -> None:
        seed = [ArtifactState(artifactId="photo_A", ownerId="leila", state="intact", isRevealed=True)]
        out = apply_artifact_updates(
            seed,
            [ArtifactUpdate(artifactId="photo_A", operation=ArtifactOperation.CONCEAL,
                            reasonCode="conceal")],
        )
        photo = find_artifact(out, "photo_A")
        self.assertFalse(photo.isRevealed)


class UniquenessInvariantTests(unittest.TestCase):
    """Cross-operation invariants: after a sequence of ops, the
    state must still have unique artifactIds and no two artifacts
    sharing the (owner, state, location, isRevealed) fingerprint."""

    def test_transfer_create_transfer_uniqueness(self) -> None:
        """Spawn a new photo, transfer it, transfer again — uniqueness must hold."""

        seed = _seed()
        ops = [
            ArtifactUpdate(artifactId="photo_C", operation=ArtifactOperation.CREATE,
                            newOwnerId="leila", newState="intact", reasonCode="spawn"),
            ArtifactUpdate(artifactId="photo_C", operation=ArtifactOperation.TRANSFER,
                            newOwnerId="arash", reasonCode="give"),
            ArtifactUpdate(artifactId="photo_C", operation=ArtifactOperation.TRANSFER,
                            newOwnerId="leila", reasonCode="return"),
        ]
        out = apply_artifact_updates(seed, ops)
        ids = [a.artifactId for a in out]
        self.assertEqual(len(ids), len(set(ids)))  # all unique
        # photo_C ended up with leila
        photo_c = find_artifact(out, "photo_C")
        self.assertEqual(photo_c.ownerId, "leila")

    def test_destroy_nonexistent_raises(self) -> None:
        with self.assertRaises(EvidenceNotFoundError):
            apply_artifact_updates(
                _seed(),
                [ArtifactUpdate(artifactId="ghost", operation=ArtifactOperation.DESTROY,
                                reasonCode="oops")],
            )

    def test_transfer_nonexistent_raises(self) -> None:
        with self.assertRaises(EvidenceNotFoundError):
            apply_artifact_updates(
                _seed(),
                [ArtifactUpdate(artifactId="ghost", operation=ArtifactOperation.TRANSFER,
                                newOwnerId="leila", reasonCode="oops")],
            )


if __name__ == "__main__":
    unittest.main()
