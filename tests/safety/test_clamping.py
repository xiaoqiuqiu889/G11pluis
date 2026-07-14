"""Unit tests for the numeric clamping layer (校验链 physical-boundary gate).

The brief mandates the following quanta and ranges (mirror
``server/engine/types.py`` and the JSON-Schema ``multipleOf``
declarations):

* trust / intimacy ∈ [-1, 1], |delta| ≤ 0.25, 0.01 quantum
* eventSequence ∈ [0, 100000], integer
* echo_intensity ∈ [0, 1], 0.01 quantum
* All floats are multiples of their quantum (multipleOf)

Every numeric value the LLM emits is suspect; this test
covers:

* The four numeric predicates (``is_legal_*``)
* The snap-to-quantum edge cases (notably 0.95/0.01)
* The audit log records what was clamped, to what, and why
* NaN / +inf / -inf handling
* FieldKind dispatch via :func:`clamp_field`
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.safety.clamping import (  # noqa: E402
    ClampEvent,
    ClampingAudit,
    ClampRequest,
    FIELD_SPECS,
    FieldKind,
    _is_finite,
    _snap_to_quantum,
    clamp_field,
    clamp_many,
    clamp_to_range,
    is_legal_echo_intensity,
    is_legal_event_sequence,
    is_legal_relationship,
    is_legal_relationship_delta,
    is_legal_unit,
)


class SnapToQuantumTests(unittest.TestCase):
    """``_snap_to_quantum`` must dodge the 0.95/0.01 floating-point hazard."""

    def test_zero_point_ninety_five_snap_to_hundredth(self) -> None:
        # 0.95 is the canonical case — naive round produces 0.94.
        snapped = _snap_to_quantum(0.95, 0.01)
        self.assertEqual(snapped, 0.95)

    def test_zero_point_ninety_four_snap_to_hundredth(self) -> None:
        self.assertEqual(_snap_to_quantum(0.94, 0.01), 0.94)

    def test_one_third_rounds_half_up(self) -> None:
        # 0.075 / 0.01 = 7.5 → 8 (ROUND_HALF_UP)
        self.assertEqual(_snap_to_quantum(0.075, 0.01), 0.08)

    def test_negative_round_trip(self) -> None:
        self.assertEqual(_snap_to_quantum(-0.95, 0.01), -0.95)
        self.assertEqual(_snap_to_quantum(-0.94, 0.01), -0.94)

    def test_integer_quantum(self) -> None:
        self.assertEqual(_snap_to_quantum(5.4, 1.0), 5.0)
        self.assertEqual(_snap_to_quantum(5.6, 1.0), 6.0)
        self.assertEqual(_snap_to_quantum(5.5, 1.0), 6.0)  # half-up

    def test_invalid_quantum_raises(self) -> None:
        with self.assertRaises(ValueError):
            _snap_to_quantum(0.5, 0.0)
        with self.assertRaises(ValueError):
            _snap_to_quantum(0.5, -0.01)


class IsLegalPredicateTests(unittest.TestCase):
    """The five ``is_legal_*`` predicates."""

    # ---- unit ---------------------------------------------------------

    def test_unit_predicate_basic(self) -> None:
        self.assertTrue(is_legal_unit(0.0))
        self.assertTrue(is_legal_unit(1.0))
        self.assertTrue(is_legal_unit(0.95))
        self.assertFalse(is_legal_unit(-0.01))
        self.assertFalse(is_legal_unit(1.01))

    def test_unit_predicate_quantum(self) -> None:
        self.assertTrue(is_legal_unit(0.01))
        self.assertTrue(is_legal_unit(0.99))
        # 0.005 is not a multiple of 0.01
        self.assertFalse(is_legal_unit(0.005))
        # 0.075 → 0.08 with ROUND_HALF_UP
        self.assertFalse(is_legal_unit(0.075))

    def test_unit_predicate_nan_inf(self) -> None:
        self.assertFalse(is_legal_unit(float("nan")))
        self.assertFalse(is_legal_unit(float("inf")))
        self.assertFalse(is_legal_unit(float("-inf")))

    # ---- relationship -------------------------------------------------

    def test_relationship_predicate_basic(self) -> None:
        self.assertTrue(is_legal_relationship(-1.0))
        self.assertTrue(is_legal_relationship(0.0))
        self.assertTrue(is_legal_relationship(1.0))
        self.assertTrue(is_legal_relationship(0.95))
        self.assertFalse(is_legal_relationship(-1.01))
        self.assertFalse(is_legal_relationship(1.01))

    def test_relationship_predicate_quantum(self) -> None:
        self.assertTrue(is_legal_relationship(0.01))
        self.assertFalse(is_legal_relationship(0.005))

    # ---- relationship delta -------------------------------------------

    def test_relationship_delta_predicate_within_cap(self) -> None:
        self.assertTrue(is_legal_relationship_delta(0.0))
        self.assertTrue(is_legal_relationship_delta(0.25))
        self.assertTrue(is_legal_relationship_delta(-0.25))
        self.assertTrue(is_legal_relationship_delta(0.10))
        # Beyond cap (|delta| > 0.25)
        self.assertFalse(is_legal_relationship_delta(0.26))
        self.assertFalse(is_legal_relationship_delta(-0.30))

    def test_relationship_delta_predicate_quantum(self) -> None:
        self.assertTrue(is_legal_relationship_delta(0.01))
        self.assertFalse(is_legal_relationship_delta(0.005))

    # ---- event sequence -----------------------------------------------

    def test_event_sequence_predicate_basic(self) -> None:
        self.assertTrue(is_legal_event_sequence(0))
        self.assertTrue(is_legal_event_sequence(1))
        self.assertTrue(is_legal_event_sequence(100_000))
        self.assertFalse(is_legal_event_sequence(-1))
        self.assertFalse(is_legal_event_sequence(100_001))

    def test_event_sequence_predicate_must_be_integer(self) -> None:
        self.assertFalse(is_legal_event_sequence(1.5))
        self.assertFalse(is_legal_event_sequence(0.01))

    def test_event_sequence_predicate_nan(self) -> None:
        self.assertFalse(is_legal_event_sequence(float("nan")))

    # ---- echo intensity -----------------------------------------------

    def test_echo_intensity_predicate(self) -> None:
        self.assertTrue(is_legal_echo_intensity(0.0))
        self.assertTrue(is_legal_echo_intensity(1.0))
        self.assertTrue(is_legal_echo_intensity(0.95))
        self.assertFalse(is_legal_echo_intensity(-0.01))
        self.assertFalse(is_legal_echo_intensity(1.01))
        self.assertFalse(is_legal_echo_intensity(0.005))


class ClampToRangeTests(unittest.TestCase):
    """``clamp_to_range`` enforces range, snaps to quantum, audits."""

    def test_in_range_no_audit(self) -> None:
        audit = ClampingAudit()
        out = clamp_to_range(0.5, lo=0.0, hi=1.0, quantum=0.01, path="x", audit=audit)
        self.assertEqual(out, 0.5)
        self.assertEqual(len(audit), 0)

    def test_below_min_clamped_to_min(self) -> None:
        audit = ClampingAudit()
        out = clamp_to_range(-0.1, lo=0.0, hi=1.0, quantum=0.01, path="x", audit=audit)
        self.assertEqual(out, 0.0)
        self.assertEqual(len(audit), 1)
        e = audit.events[0]
        self.assertEqual(e.reason, "below_min")
        self.assertEqual(e.path, "x")
        self.assertEqual(e.original, -0.1)
        self.assertEqual(e.applied, 0.0)
        self.assertEqual(e.min, 0.0)
        self.assertEqual(e.max, 1.0)

    def test_above_max_clamped_to_max(self) -> None:
        audit = ClampingAudit()
        out = clamp_to_range(5.0, lo=0.0, hi=1.0, quantum=0.01, path="y", audit=audit)
        self.assertEqual(out, 1.0)
        self.assertEqual(audit.events[0].reason, "above_max")

    def test_snap_to_quantum_audited(self) -> None:
        audit = ClampingAudit()
        out = clamp_to_range(0.075, lo=0.0, hi=1.0, quantum=0.01, path="z", audit=audit)
        # 0.075 → 0.08 (half-up)
        self.assertEqual(out, 0.08)
        self.assertEqual(audit.events[0].reason, "not_multiple_of")
        self.assertEqual(audit.events[0].original, 0.075)
        self.assertEqual(audit.events[0].applied, 0.08)

    def test_nan_audited_and_returns_hi(self) -> None:
        audit = ClampingAudit()
        out = clamp_to_range(float("nan"), lo=0.0, hi=1.0, quantum=0.01, path="n", audit=audit)
        self.assertEqual(out, 1.0)
        self.assertEqual(audit.events[0].reason, "nan")
        self.assertTrue(math.isnan(audit.events[0].original))

    def test_positive_inf_audited_and_returns_hi(self) -> None:
        audit = ClampingAudit()
        out = clamp_to_range(float("inf"), lo=0.0, hi=1.0, quantum=0.01, path="i", audit=audit)
        self.assertEqual(out, 1.0)
        self.assertEqual(audit.events[0].reason, "infinity")

    def test_negative_inf_audited_and_returns_lo(self) -> None:
        audit = ClampingAudit()
        out = clamp_to_range(float("-inf"), lo=0.0, hi=1.0, quantum=0.01, path="j", audit=audit)
        self.assertEqual(out, 0.0)
        self.assertEqual(audit.events[0].reason, "infinity")

    def test_nan_raises_without_audit(self) -> None:
        with self.assertRaises(ValueError):
            clamp_to_range(float("nan"), lo=0.0, hi=1.0, quantum=0.01, path="k")

    def test_inf_raises_without_audit(self) -> None:
        with self.assertRaises(ValueError):
            clamp_to_range(float("inf"), lo=0.0, hi=1.0, quantum=0.01, path="k")


class ClampFieldTests(unittest.TestCase):
    """``clamp_field`` dispatches to the right (lo, hi, quantum)."""

    def test_all_field_kinds_have_specs(self) -> None:
        for kind in FieldKind:
            self.assertIn(kind, FIELD_SPECS)

    def test_relationship_range(self) -> None:
        out = clamp_field(FieldKind.RELATIONSHIP, 1.5, path="r", audit=ClampingAudit())
        self.assertEqual(out, 1.0)
        out = clamp_field(FieldKind.RELATIONSHIP, -1.5, path="r", audit=ClampingAudit())
        self.assertEqual(out, -1.0)

    def test_relationship_delta_hard_cap(self) -> None:
        # The |delta| ≤ 0.25 cap is enforced here
        out = clamp_field(FieldKind.RELATIONSHIP_DELTA, 0.5, path="d", audit=ClampingAudit())
        self.assertEqual(out, 0.25)
        out = clamp_field(FieldKind.RELATIONSHIP_DELTA, -0.4, path="d", audit=ClampingAudit())
        self.assertEqual(out, -0.25)

    def test_event_sequence_integer(self) -> None:
        out = clamp_field(FieldKind.EVENT_SEQUENCE, 100, path="e", audit=ClampingAudit())
        self.assertEqual(out, 100.0)
        out = clamp_field(FieldKind.EVENT_SEQUENCE, 100_001, path="e", audit=ClampingAudit())
        self.assertEqual(out, 100_000.0)

    def test_unit_emotion_pacing_use_005_quantum(self) -> None:
        # emotion / pacing are 0..1 with 0.05 quantum
        out = clamp_field(FieldKind.EMOTION, 0.04, path="emo", audit=ClampingAudit())
        self.assertEqual(out, 0.05)  # round-up
        out = clamp_field(FieldKind.PACING, 0.06, path="pac", audit=ClampingAudit())
        self.assertEqual(out, 0.05)  # round-down (6/5 = 1.2 → 1)

    def test_tension_delta_can_be_negative(self) -> None:
        out = clamp_field(FieldKind.TENSION_DELTA, -0.5, path="t", audit=ClampingAudit())
        self.assertEqual(out, -0.5)
        out = clamp_field(FieldKind.TENSION_DELTA, 1.5, path="t", audit=ClampingAudit())
        self.assertEqual(out, 1.0)

    def test_echo_intensity_001_quantum(self) -> None:
        out = clamp_field(FieldKind.ECHO_INTENSITY, 0.95, path="ei", audit=ClampingAudit())
        self.assertEqual(out, 0.95)
        out = clamp_field(FieldKind.ECHO_INTENSITY, 0.075, path="ei", audit=ClampingAudit())
        self.assertEqual(out, 0.08)

    def test_unknown_kind_raises(self) -> None:
        with self.assertRaises(KeyError):
            clamp_field("not_a_real_kind", 0.5)  # type: ignore[arg-type]


class ClampManyTests(unittest.TestCase):
    """``clamp_many`` applies a batch of requests against a shared audit."""

    def test_batch_returns_path_to_value(self) -> None:
        audit = ClampingAudit()
        requests = [
            ClampRequest(kind=FieldKind.UNIT, value=0.95, path="trust"),
            ClampRequest(kind=FieldKind.RELATIONSHIP_DELTA, value=0.5, path="delta"),
            ClampRequest(kind=FieldKind.EVENT_SEQUENCE, value=42, path="seq"),
        ]
        out = clamp_many(requests, audit=audit)
        self.assertEqual(out["trust"], 0.95)
        self.assertEqual(out["delta"], 0.25)  # cap
        self.assertEqual(out["seq"], 42.0)
        # The trust / seq clamps should not be audited; only the
        # delta cap should be.
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit.events[0].path, "delta")

    def test_batch_audit_none_creates_no_audit(self) -> None:
        requests = [ClampRequest(kind=FieldKind.UNIT, value=0.5, path="x")]
        out = clamp_many(requests)  # no audit
        self.assertEqual(out["x"], 0.5)


class AuditDataClassTests(unittest.TestCase):
    """``ClampEvent`` and ``ClampingAudit`` are JSON-serialisable."""

    def test_event_to_dict(self) -> None:
        e = ClampEvent(
            path="x", original=1.5, applied=1.0, min=0.0, max=1.0, reason="above_max"
        )
        d = e.to_dict()
        self.assertEqual(d["path"], "x")
        self.assertEqual(d["original"], 1.5)
        self.assertEqual(d["applied"], 1.0)
        self.assertEqual(d["reason"], "above_max")

    def test_audit_to_dict_round_trip(self) -> None:
        import json
        audit = ClampingAudit()
        audit.record(ClampEvent(
            path="y", original=0.0, applied=0.0, min=0.0, max=1.0, reason="below_min"
        ))
        s = json.dumps(audit.to_dict())
        reloaded = json.loads(s)
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0]["path"], "y")

    def test_audit_iter_and_len(self) -> None:
        audit = ClampingAudit()
        self.assertEqual(len(audit), 0)
        audit.record(ClampEvent(path="a", original=0.0, applied=0.0, min=0.0, max=1.0, reason="below_min"))
        self.assertEqual(len(audit), 1)
        for _ in audit:
            pass  # iter works


class IsFiniteTests(unittest.TestCase):
    """``_is_finite`` is the NaN/Inf detector."""

    def test_finite(self) -> None:
        self.assertTrue(_is_finite(0.0))
        self.assertTrue(_is_finite(-0.0))
        self.assertTrue(_is_finite(0.5))
        self.assertTrue(_is_finite(1e10))

    def test_non_finite(self) -> None:
        self.assertFalse(_is_finite(float("nan")))
        self.assertFalse(_is_finite(float("inf")))
        self.assertFalse(_is_finite(float("-inf")))


if __name__ == "__main__":
    unittest.main()
