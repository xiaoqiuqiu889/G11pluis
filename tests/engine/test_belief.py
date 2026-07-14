"""Belief matrix — 5-state transition tests.

Per the belief_matrix.schema.json, each character's
``character_knowledge`` entry can be in one of 5 states:

* ``certain`` — character knows the truth
* ``uncertain`` — character is unsure
* ``wrong`` — character holds a false belief
* ``denied`` — character actively refuses
* ``reinforced`` — character's belief was just re-confirmed

The 5-state transition rules in this engine:

* no-op (from == to) is rejected
* all cross-state transitions are legal at the matrix level
  (the Resolver enforces contract-level rules)
"""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, "server")

from engine import (  # noqa: E402
    BELIEF_STATES,
    BeliefMatrix,
    BeliefMatrixStore,
    BeliefState,
    CharacterKnowledge,
    DistortionType,
    HiddenSecret,
    MemoryEntry,
    ObjectiveFact,
)
from engine.exceptions import ValidationError  # noqa: E402


class BeliefStateEnumTests(unittest.TestCase):

    def test_exactly_five_states(self) -> None:
        self.assertEqual(len(BELIEF_STATES), 5)
        self.assertEqual(
            BELIEF_STATES,
            {"certain", "uncertain", "wrong", "denied", "reinforced"},
        )

    def test_legal_transition_rejects_noop(self) -> None:
        for s in BeliefState:
            self.assertFalse(BeliefMatrix.legal_transition(s.value, s.value))

    def test_legal_transition_rejects_unset(self) -> None:
        for s in BeliefState:
            self.assertFalse(BeliefMatrix.legal_transition(s.value, "unset"))

    def test_legal_transition_allows_different(self) -> None:
        for s1 in BeliefState:
            for s2 in BeliefState:
                if s1 is not s2:
                    self.assertTrue(BeliefMatrix.legal_transition(s1.value, s2.value))


class BeliefMatrixTests(unittest.TestCase):
    """A BeliefMatrix is a per-character 4-layer model."""

    def test_create_empty(self) -> None:
        m = BeliefMatrix(characterId="leila")
        self.assertEqual(m.characterId, "leila")
        self.assertEqual(m.objective_facts, [])
        self.assertEqual(m.character_knowledge, [])
        self.assertEqual(m.character_memories, [])
        self.assertEqual(m.hidden_secrets, [])

    def test_apply_update_creates_new_entry(self) -> None:
        m = BeliefMatrix(characterId="leila")
        m.apply_update(subject="photo_A", new_state="certain", confidence=0.9, sequence=1)
        k = m.find_knowledge("photo_A")
        self.assertIsNotNone(k)
        self.assertEqual(k.belief_state, "certain")
        self.assertEqual(k.confidence, 0.9)

    def test_apply_update_overwrites_existing(self) -> None:
        m = BeliefMatrix(characterId="leila")
        m.apply_update(subject="photo_A", new_state="uncertain", confidence=0.4, sequence=1)
        m.apply_update(subject="photo_A", new_state="certain", confidence=0.95, sequence=2)
        k = m.find_knowledge("photo_A")
        self.assertEqual(k.belief_state, "certain")
        self.assertEqual(k.confidence, 0.95)
        # There is exactly one entry, not two
        self.assertEqual(len([x for x in m.character_knowledge if x.subject == "photo_A"]), 1)

    def test_apply_update_rejects_invalid_state(self) -> None:
        m = BeliefMatrix(characterId="leila")
        with self.assertRaises(ValidationError):
            m.apply_update(subject="x", new_state="bogus", confidence=0.5)

    def test_confidence_is_clamped(self) -> None:
        m = BeliefMatrix(characterId="leila")
        m.apply_update(subject="x", new_state="certain", confidence=1.5, sequence=1)
        k = m.find_knowledge("x")
        self.assertLessEqual(k.confidence, 1.0)
        m.apply_update(subject="y", new_state="certain", confidence=-0.3, sequence=1)
        k = m.find_knowledge("y")
        self.assertGreaterEqual(k.confidence, 0.0)

    def test_knows_secret(self) -> None:
        m = BeliefMatrix(characterId="leila")
        s = HiddenSecret(secretId="s1", content="...", isSecret=True,
                         knownByCharacterIds=["leila", "arash"])
        m.hidden_secrets.append(s)
        self.assertTrue(m.knows_secret("s1", "leila"))
        self.assertTrue(m.knows_secret("s1", "arash"))
        self.assertFalse(m.knows_secret("s1", "maziar"))
        self.assertFalse(m.knows_secret("s2", "leila"))


class BeliefMatrixStoreTests(unittest.TestCase):
    """Per-run store of multiple matrices."""

    def test_get_or_create(self) -> None:
        s = BeliefMatrixStore()
        m = s.get_or_create("leila")
        self.assertEqual(m.characterId, "leila")
        self.assertEqual(len(s), 1)
        # Calling again returns the same matrix
        m2 = s.get_or_create("leila")
        self.assertIs(m, m2)
        self.assertEqual(len(s), 1)

    def test_upsert(self) -> None:
        s = BeliefMatrixStore()
        m = BeliefMatrix(characterId="arash")
        m.objective_facts.append(ObjectiveFact(factId="f1", description="...",
                                               establishedAt=1, isContested=False))
        s.upsert(m)
        self.assertEqual(len(s.get("arash").objective_facts), 1)

    def test_to_from_list(self) -> None:
        s = BeliefMatrixStore()
        s.get_or_create("leila").apply_update(subject="x", new_state="certain", confidence=0.5, sequence=1)
        s.get_or_create("arash").apply_update(subject="y", new_state="uncertain", confidence=0.4, sequence=1)
        data = s.to_list()
        s2 = BeliefMatrixStore.from_list(data)
        self.assertEqual(len(s2), 2)
        self.assertEqual(s2.get("leila").find_knowledge("x").belief_state, "certain")


class DistortionTypeTests(unittest.TestCase):
    """10 distortion types are supported."""

    def test_all_ten(self) -> None:
        self.assertEqual(len(set(d.value for d in DistortionType)), 10)


if __name__ == "__main__":
    unittest.main()
