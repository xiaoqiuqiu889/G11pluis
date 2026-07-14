"""Unit tests for the idempotency / replay-key gate.

The brief specifies three exit codes:

* 0 = pass
* 1 = block
* 2 = I/O error

Coverage:

* ``audit_idempotency_keys`` — duplicate ``idempotencyKey``
* ``scan_client_action_replays`` — duplicate ``clientActionId``
* ``audit_file`` — file I/O + combined exit code
* ``ExitCode`` is the canonical exit-code enum
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.safety.idempotency import (  # noqa: E402
    ExitCode,
    IdempotencyReport,
    IdempotencyViolation,
    audit_file,
    audit_idempotency_keys,
    load_log,
    scan_client_action_replays,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _clean_log() -> list[dict]:
    return [
        {
            "sequence": 1,
            "actorId": "leila",
            "idempotencyKey": "k1",
            "actionPayload": {"clientActionId": "caid_1"},
        },
        {
            "sequence": 2,
            "actorId": "arash",
            "idempotencyKey": "k2",
            "actionPayload": {"clientActionId": "caid_2"},
        },
    ]


# ---------------------------------------------------------------------------
# IdempotencyKey audit
# ---------------------------------------------------------------------------


class IdempotencyKeyAuditTests(unittest.TestCase):
    def test_unique_keys_pass(self) -> None:
        r = audit_idempotency_keys(_clean_log())
        self.assertTrue(r.passed)
        self.assertEqual(r.exit_code, int(ExitCode.PASS))
        self.assertEqual(r.violations, [])

    def test_duplicate_key_caught(self) -> None:
        log = _clean_log()
        log.append({
            "sequence": 3,
            "actorId": "leila",
            "idempotencyKey": "k1",  # dup
            "actionPayload": {"clientActionId": "caid_3"},
        })
        r = audit_idempotency_keys(log)
        self.assertFalse(r.passed)
        self.assertEqual(r.exit_code, int(ExitCode.BLOCK))
        self.assertEqual(len(r.violations), 1)
        v = r.violations[0]
        self.assertEqual(v.key, "k1")
        self.assertEqual(v.key_kind, "idempotencyKey")
        self.assertEqual(v.first_seen_at, 0)
        self.assertEqual(v.duplicate_at, 2)
        self.assertEqual(v.sequence, 3)
        self.assertEqual(v.actorId, "leila")

    def test_missing_key_is_skipped(self) -> None:
        # An event with no idempotencyKey is the caller's bug but
        # the audit is non-fatal — a separate invariant (I10) tracks it.
        log = [
            {"sequence": 1, "actorId": "leila", "idempotencyKey": ""},
        ]
        r = audit_idempotency_keys(log)
        self.assertTrue(r.passed)
        self.assertEqual(r.violations, [])

    def test_non_dict_entries_skipped(self) -> None:
        log = _clean_log() + ["not a dict"]
        r = audit_idempotency_keys(log)
        self.assertTrue(r.passed)

    def test_summary_counts(self) -> None:
        log = _clean_log()
        log.append({"sequence": 3, "actorId": "x", "idempotencyKey": "k1"})
        r = audit_idempotency_keys(log)
        self.assertEqual(r.summary["idempotencyKey_duplicates"], 1)
        self.assertEqual(r.summary["unique_idempotencyKeys"], 2)


# ---------------------------------------------------------------------------
# ClientActionId audit
# ---------------------------------------------------------------------------


class ClientActionIdScanTests(unittest.TestCase):
    def test_unique_ids_pass(self) -> None:
        r = scan_client_action_replays(_clean_log())
        self.assertTrue(r.passed)
        self.assertEqual(r.exit_code, int(ExitCode.PASS))

    def test_duplicate_caid_caught(self) -> None:
        log = _clean_log()
        log.append({
            "sequence": 3,
            "actorId": "arash",
            "idempotencyKey": "k3",
            "actionPayload": {"clientActionId": "caid_1"},  # replay
        })
        r = scan_client_action_replays(log)
        self.assertFalse(r.passed)
        self.assertEqual(r.exit_code, int(ExitCode.BLOCK))
        self.assertEqual(len(r.violations), 1)
        v = r.violations[0]
        self.assertEqual(v.key_kind, "clientActionId")
        self.assertEqual(v.key, "caid_1")

    def test_window_caps_scan(self) -> None:
        # With a window of 1, we only look at the last event
        log = _clean_log() + [
            {
                "sequence": 3,
                "actorId": "arash",
                "idempotencyKey": "k3",
                "actionPayload": {"clientActionId": "caid_1"},  # replay
            }
        ]
        r_small = scan_client_action_replays(log, seen_window=1)
        # The window of 1 only inspects the last event;
        # "caid_1" is the only clientActionId in the window so no dup.
        self.assertTrue(r_small.passed)
        # Without window: the dup is found
        r_full = scan_client_action_replays(log)
        self.assertFalse(r_full.passed)

    def test_missing_payload_is_skipped(self) -> None:
        log = [{"sequence": 1, "actorId": "leila", "idempotencyKey": "k1"}]
        r = scan_client_action_replays(log)
        self.assertTrue(r.passed)

    def test_non_dict_payload_is_skipped(self) -> None:
        log = [
            {"sequence": 1, "actorId": "leila", "idempotencyKey": "k1", "actionPayload": "not a dict"},
        ]
        r = scan_client_action_replays(log)
        self.assertTrue(r.passed)


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


class FileAuditTests(unittest.TestCase):
    def test_load_list_shape(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump([{"sequence": 1, "actorId": "leila", "idempotencyKey": "k1"}], f)
            path = f.name
        try:
            events = load_log(path)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["actorId"], "leila")
        finally:
            Path(path).unlink()

    def test_load_wrapper_shape(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({
                "runId": "00000000-0000-4000-8000-000000000001",
                "events": [{"sequence": 1, "actorId": "leila", "idempotencyKey": "k1"}],
            }, f)
            path = f.name
        try:
            events = load_log(path)
            self.assertEqual(len(events), 1)
        finally:
            Path(path).unlink()

    def test_load_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_log("/no/such/file.json")

    def test_load_malformed_json_raises(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write("not json")
            path = f.name
        try:
            with self.assertRaises(json.JSONDecodeError):
                load_log(path)
        finally:
            Path(path).unlink()

    def test_audit_file_clean(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(_clean_log(), f)
            path = f.name
        try:
            r = audit_file(path)
            self.assertTrue(r.passed)
            self.assertEqual(r.exit_code, int(ExitCode.PASS))
        finally:
            Path(path).unlink()

    def test_audit_file_duplicate_key(self) -> None:
        log = _clean_log()
        log.append({
            "sequence": 3,
            "actorId": "leila",
            "idempotencyKey": "k1",
            "actionPayload": {"clientActionId": "caid_3"},
        })
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(log, f)
            path = f.name
        try:
            r = audit_file(path)
            self.assertFalse(r.passed)
            self.assertEqual(r.exit_code, int(ExitCode.BLOCK))
            self.assertEqual(r.summary["idempotencyKey_duplicates"], 1)
        finally:
            Path(path).unlink()

    def test_audit_file_io_error(self) -> None:
        r = audit_file("/no/such/file.json")
        self.assertFalse(r.passed)
        self.assertEqual(r.exit_code, int(ExitCode.IO_ERROR))
        self.assertEqual(r.summary["io_error"], 1)

    def test_audit_file_skips_replays(self) -> None:
        # Disable the replay scan; only the key audit runs
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(_clean_log(), f)
            path = f.name
        try:
            r = audit_file(path, check_replays=False)
            self.assertTrue(r.passed)
        finally:
            Path(path).unlink()


# ---------------------------------------------------------------------------
# Exit-code stability
# ---------------------------------------------------------------------------


class ExitCodeTests(unittest.TestCase):
    def test_exit_codes_are_canonical(self) -> None:
        self.assertEqual(int(ExitCode.PASS), 0)
        self.assertEqual(int(ExitCode.BLOCK), 1)
        self.assertEqual(int(ExitCode.IO_ERROR), 2)

    def test_to_human_readable_includes_verdict(self) -> None:
        r = audit_idempotency_keys(_clean_log())
        text = r.to_human_readable()
        self.assertIn("✅", text)
        self.assertIn("idempotency", text)
        self.assertIn("exit_code=0", text)

    def test_to_dict_is_json_serialisable(self) -> None:
        log = _clean_log()
        log.append({
            "sequence": 3, "actorId": "leila", "idempotencyKey": "k1",
            "actionPayload": {"clientActionId": "caid_3"},
        })
        r = audit_idempotency_keys(log)
        s = json.dumps(r.to_dict())
        reloaded = json.loads(s)
        self.assertFalse(reloaded["passed"])
        self.assertEqual(reloaded["exit_code"], 1)
        self.assertEqual(len(reloaded["violations"]), 1)


if __name__ == "__main__":
    unittest.main()
