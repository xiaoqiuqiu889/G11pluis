"""4-level degradation chain tests.

Verifies, for each of L1/L2/L3/L4, that:

* the trigger condition fires on the right failure
* the chain's level is monotonically non-decreasing
* the fallback action returns the right payload
* the diagnostic record captures the trigger
"""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, "server")

from engine import (  # noqa: E402
    DegradationChain,
    DegradationLevel,
    FallbackScript,
    LEVEL_ORDER,
    NPCFallbackLine,
    with_director_timeout_skip,
    with_hard_degradation,
    with_npc_timeout_fallback,
    with_persist_failure,
)
from engine.exceptions import (  # noqa: E402
    DirectorTimeoutError,
    HardDegradationError,
    NPCTimeoutError,
    PersistFailureError,
)


def _script() -> FallbackScript:
    return FallbackScript(
        sceneId="photo_lab_2008",
        npc_lines=[
            NPCFallbackLine(
                characterId="arash",
                sceneId="photo_lab_2008",
                actionType="comfort",
                line="[fallback] Arash says nothing; the projector hums.",
            ),
        ],
        director_skip_line="[fallback] The projector light flickers; the beat skips.",
        hard_lines={
            "beat_divide_photos": "[hard] Leila looks at the photo, then at Arash.",
        },
        persist_message="服务暂不可用，本轮进度已为您保留。",
    )


# ---------------------------------------------------------------------------
# L1: NPC timeout
# ---------------------------------------------------------------------------


class L1NPCTimeoutTests(unittest.TestCase):

    def test_l1_fires_on_npc_timeout(self) -> None:
        chain = DegradationChain(sceneId="photo_lab_2008")
        script = _script()

        def npc_call() -> None:
            raise NPCTimeoutError("simulated 4s deadline")

        result, used_fallback = with_npc_timeout_fallback(
            chain=chain, fallback=script,
            characterId="arash", actionType="comfort",
            npc_call=npc_call, timeout_seconds=0.0,
        )
        self.assertTrue(used_fallback)
        self.assertIsNotNone(result)
        self.assertEqual(result.line, "[fallback] Arash says nothing; the projector hums.")
        self.assertEqual(chain.current_level, DegradationLevel.L1_NPC_TIMEOUT)
        self.assertEqual(len(chain.records), 1)
        self.assertEqual(chain.records[0].trigger, "npc_timeout")

    def test_l1_does_not_fire_on_success(self) -> None:
        chain = DegradationChain(sceneId="photo_lab_2008")
        script = _script()

        def npc_call() -> str:
            return "live agent response"

        result, used_fallback = with_npc_timeout_fallback(
            chain=chain, fallback=script,
            characterId="arash", actionType="comfort",
            npc_call=npc_call, timeout_seconds=1.0,
        )
        self.assertFalse(used_fallback)
        self.assertEqual(result, "live agent response")
        self.assertIsNone(chain.current_level)


# ---------------------------------------------------------------------------
# L2: Director timeout
# ---------------------------------------------------------------------------


class L2DirectorTimeoutTests(unittest.TestCase):

    def test_l2_fires_on_director_timeout(self) -> None:
        chain = DegradationChain(sceneId="photo_lab_2008")
        script = _script()

        def director_call() -> None:
            raise DirectorTimeoutError("simulated 4s deadline")

        result, used_skip = with_director_timeout_skip(
            chain=chain, fallback=script,
            director_call=director_call, timeout_seconds=0.0,
        )
        self.assertTrue(used_skip)
        self.assertIsNone(result)
        self.assertEqual(chain.current_level, DegradationLevel.L2_DIRECTOR_TIMEOUT)

    def test_l2_does_not_fire_on_success(self) -> None:
        chain = DegradationChain(sceneId="photo_lab_2008")
        script = _script()

        def director_call() -> str:
            return "live director beat"

        result, used_skip = with_director_timeout_skip(
            chain=chain, fallback=script,
            director_call=director_call, timeout_seconds=1.0,
        )
        self.assertFalse(used_skip)
        self.assertEqual(result, "live director beat")
        self.assertIsNone(chain.current_level)


# ---------------------------------------------------------------------------
# L3: Hard degradation (two consecutive failures)
# ---------------------------------------------------------------------------


class L3HardDegradationTests(unittest.TestCase):

    def test_l3_fires_after_two_consecutive_director_failures(self) -> None:
        chain = DegradationChain(sceneId="photo_lab_2008")
        script = _script()

        def director_call() -> None:
            raise DirectorTimeoutError("first fail")

        with_director_timeout_skip(chain=chain, fallback=script, director_call=director_call, timeout_seconds=0.0)
        # After the first failure, chain is at L2
        self.assertEqual(chain.current_level, DegradationLevel.L2_DIRECTOR_TIMEOUT)

        def director_call2() -> None:
            raise DirectorTimeoutError("second fail")

        with_director_timeout_skip(chain=chain, fallback=script, director_call=director_call2, timeout_seconds=0.0)
        # After the second failure, chain escalates to L3
        self.assertEqual(chain.current_level, DegradationLevel.L3_HARD_DEGRADATION)
        self.assertTrue(chain.is_at_least(DegradationLevel.L3_HARD_DEGRADATION))

    def test_l3_hard_line_lookup(self) -> None:
        chain = DegradationChain(sceneId="photo_lab_2008")
        chain.escalate(to=DegradationLevel.L3_HARD_DEGRADATION, trigger="x2_director_timeout")
        line = with_hard_degradation(chain=chain, fallback=_script(), beatId="beat_divide_photos")
        self.assertEqual(line, "[hard] Leila looks at the photo, then at Arash.")

    def test_l3_rejected_when_not_active(self) -> None:
        chain = DegradationChain(sceneId="photo_lab_2008")
        with self.assertRaises(HardDegradationError):
            with_hard_degradation(chain=chain, fallback=_script(), beatId="beat_divide_photos")


# ---------------------------------------------------------------------------
# L4: Persist failure
# ---------------------------------------------------------------------------


class L4PersistFailureTests(unittest.TestCase):

    def test_l4_fires_on_persist_failure(self) -> None:
        chain = DegradationChain(sceneId="photo_lab_2008")
        script = _script()

        def persist_call() -> None:
            raise PersistFailureError("simulated DB outage")

        with self.assertRaises(PersistFailureError):
            with_persist_failure(chain=chain, fallback=script, persist_call=persist_call)
        self.assertEqual(chain.current_level, DegradationLevel.L4_PERSIST_FAILURE)
        self.assertTrue(chain.is_at_least(DegradationLevel.L4_PERSIST_FAILURE))

    def test_l4_does_not_fire_on_success(self) -> None:
        chain = DegradationChain(sceneId="photo_lab_2008")
        script = _script()

        def persist_call() -> str:
            return "ok"

        result = with_persist_failure(chain=chain, fallback=script, persist_call=persist_call)
        self.assertEqual(result, "ok")
        self.assertIsNone(chain.current_level)


# ---------------------------------------------------------------------------
# Monotonicity + ordering
# ---------------------------------------------------------------------------


class ChainOrderingTests(unittest.TestCase):

    def test_level_order(self) -> None:
        self.assertEqual(
            LEVEL_ORDER,
            (
                DegradationLevel.L1_NPC_TIMEOUT,
                DegradationLevel.L2_DIRECTOR_TIMEOUT,
                DegradationLevel.L3_HARD_DEGRADATION,
                DegradationLevel.L4_PERSIST_FAILURE,
            ),
        )

    def test_chain_is_monotonic(self) -> None:
        chain = DegradationChain(sceneId="x")
        chain.escalate(to=DegradationLevel.L2_DIRECTOR_TIMEOUT, trigger="t")
        # Try to go back to L1: should not
        chain.escalate(to=DegradationLevel.L1_NPC_TIMEOUT, trigger="t")
        self.assertEqual(chain.current_level, DegradationLevel.L2_DIRECTOR_TIMEOUT)

    def test_is_at_least(self) -> None:
        chain = DegradationChain(sceneId="x")
        chain.escalate(to=DegradationLevel.L3_HARD_DEGRADATION, trigger="t")
        self.assertTrue(chain.is_at_least(DegradationLevel.L1_NPC_TIMEOUT))
        self.assertTrue(chain.is_at_least(DegradationLevel.L2_DIRECTOR_TIMEOUT))
        self.assertTrue(chain.is_at_least(DegradationLevel.L3_HARD_DEGRADATION))
        self.assertFalse(chain.is_at_least(DegradationLevel.L4_PERSIST_FAILURE))

    def test_consecutive_failures_resets_on_success(self) -> None:
        chain = DegradationChain(sceneId="x")
        chain.note_failure()
        chain.note_failure()
        self.assertEqual(chain.consecutive_failures, 2)
        chain.reset_consecutive()
        self.assertEqual(chain.consecutive_failures, 0)


if __name__ == "__main__":
    unittest.main()
