"""
test_replay_lab.py
==================
Tests for the replay-lab reducer and CLI.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(_TOOLS))

# Use the ``replay_lab.replay`` sub-module to avoid clashing with any
# top-level ``replay`` module.
_REPLAY_DIR = _TOOLS / "replay-lab"

_spec = importlib.util.spec_from_file_location(
    "_replay_lab_replay_under_test", _REPLAY_DIR / "replay.py"
)
replay = importlib.util.module_from_spec(_spec)  # type: ignore[assignment]
sys.modules["_replay_lab_replay_under_test"] = replay  # dataclasses needs this
_spec.loader.exec_module(replay)  # type: ignore[union-attr]

import four_questions_guard_lib as guard  # noqa: E402


def _load_cli_module():
    cli_path = _REPLAY_DIR / "cli.py"
    # The CLI does `import replay` (top-level).  Pre-register our
    # already-loaded replay module under that name so the inner
    # ``import replay`` resolves to it.
    sys.modules.setdefault("replay", replay)
    spec = importlib.util.spec_from_file_location("replay_lab_cli", cli_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["replay_lab_cli"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_web_module():
    web_path = _REPLAY_DIR / "web.py"
    sys.modules.setdefault("replay", replay)
    spec = importlib.util.spec_from_file_location("replay_lab_web_test", web_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["replay_lab_web_test"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class TestReplayReducer(unittest.TestCase):

    def test_empty_event_list_is_noop(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        result = replay.replay(snap, [])
        self.assertEqual(result.events_applied, 0)
        self.assertEqual(result.events_skipped, 0)
        self.assertEqual(snap["eventSequence"], 0)  # input not mutated

    def test_applies_artifact_update(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        snap["artifactState"] = [
            {"artifactId": "photo_pair", "ownerId": "leila", "state": "in_hand", "isRevealed": True},
        ]
        ev = replay.EventLogEntry(
            eventSequence=1, outcomeId="o1", timestamp="2026-07-14T12:00:00Z",
            sceneId="photo_lab_2008", actionType="give",
            artifact_updates=[{
                "artifactId": "photo_pair",
                "newOwnerId": "arash",
                "newState": "in_book",
            }],
        )
        result = replay.replay(snap, [ev])
        self.assertEqual(result.events_applied, 1)
        art = result.final_snapshot["artifactState"][0]
        self.assertEqual(art["ownerId"], "arash")
        self.assertEqual(art["state"], "in_book")

    def test_appends_new_artifact(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        ev = replay.EventLogEntry(
            eventSequence=1, outcomeId="o1", timestamp="t",
            artifact_updates=[{
                "artifactId": "poem",
                "newOwnerId": "arash",
                "newState": "in_toolbox",
            }],
        )
        result = replay.replay(snap, [ev])
        self.assertEqual(len(result.final_snapshot["artifactState"]), 1)
        self.assertEqual(result.final_snapshot["artifactState"][0]["artifactId"], "poem")

    def test_applies_belief_update_to_existing_matrix(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        snap["beliefMatrices"] = [
            {"characterId": "arash", "character_knowledge": [], "schemaVersion": "1.0.0",
             "objective_facts": [], "character_memories": [], "hidden_secrets": []},
        ]
        ev = replay.EventLogEntry(
            eventSequence=1, outcomeId="o1", timestamp="t",
            belief_updates=[{
                "characterId": "arash",
                "subject": "photo_ownership",
                "belief_state": "certain",
                "confidence": 0.9,
            }],
        )
        result = replay.replay(snap, [ev])
        matrix = result.final_snapshot["beliefMatrices"][0]
        self.assertEqual(len(matrix["character_knowledge"]), 1)
        self.assertEqual(matrix["character_knowledge"][0]["subject"], "photo_ownership")

    def test_creates_belief_matrix_if_missing(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        ev = replay.EventLogEntry(
            eventSequence=1, outcomeId="o1", timestamp="t",
            belief_updates=[{
                "characterId": "leila",
                "subject": "x",
                "belief_state": "uncertain",
                "confidence": 0.5,
            }],
        )
        result = replay.replay(snap, [ev])
        self.assertEqual(len(result.final_snapshot["beliefMatrices"]), 1)
        self.assertEqual(result.final_snapshot["beliefMatrices"][0]["characterId"], "leila")

    def test_appends_event_log(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        ev = replay.EventLogEntry(
            eventSequence=1, outcomeId="o1", timestamp="t",
            event_log=[{"eventId": "e1", "description": "test"}],
        )
        result = replay.replay(snap, [ev])
        self.assertIn("eventLog", result.final_snapshot)
        self.assertEqual(len(result.final_snapshot["eventLog"]), 1)

    def test_merges_causal_seed(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        ev = replay.EventLogEntry(
            eventSequence=1, outcomeId="o1", timestamp="t",
            causal_seeds=[{"seedId": "photo_in_book", "planted": True, "intensity": 0.9}],
        )
        result = replay.replay(snap, [ev])
        self.assertEqual(len(result.final_snapshot["causalSeedsActive"]), 1)
        self.assertEqual(result.final_snapshot["causalSeedsActive"][0]["id"], "photo_in_book")

    def test_advances_turn_index(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        ev = replay.EventLogEntry(
            eventSequence=1, outcomeId="o1", timestamp="t", turn_index=3,
        )
        result = replay.replay(snap, [ev])
        self.assertEqual(result.final_snapshot["canonicalState"]["turnIndex"], 3)

    def test_sorts_out_of_order_events(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        ev3 = replay.EventLogEntry(eventSequence=3, outcomeId="o3", timestamp="t", turn_index=3)
        ev1 = replay.EventLogEntry(eventSequence=1, outcomeId="o1", timestamp="t", turn_index=1)
        ev2 = replay.EventLogEntry(eventSequence=2, outcomeId="o2", timestamp="t", turn_index=2)
        result = replay.replay(snap, [ev3, ev1, ev2])
        self.assertEqual([t.eventSequence for t in result.trace], [1, 2, 3])

    def test_stop_at_short_circuits(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        ev1 = replay.EventLogEntry(eventSequence=1, outcomeId="o1", timestamp="t", turn_index=1)
        ev2 = replay.EventLogEntry(eventSequence=2, outcomeId="o2", timestamp="t", turn_index=2)
        ev3 = replay.EventLogEntry(eventSequence=3, outcomeId="o3", timestamp="t", turn_index=3)
        # stop_at is exclusive: events with eventSequence > stop_at are
        # skipped.  So with stop_at=2, ev1 and ev2 are applied; ev3 is
        # skipped.
        result = replay.replay(snap, [ev1, ev2, ev3], stop_at=2)
        self.assertEqual(result.events_applied, 2)
        self.assertEqual(result.events_skipped, 1)
        self.assertEqual(len(result.trace), 3)
        # ev3 is the only one in the trace with a skip reason
        self.assertEqual(result.trace[2].skipped, ["stop_at=2"])
        self.assertEqual(result.trace[2].applied, [])

    def test_does_not_mutate_input_snapshot(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        ev = replay.EventLogEntry(
            eventSequence=1, outcomeId="o1", timestamp="t",
            artifact_updates=[{"artifactId": "x", "newOwnerId": "y"}],
        )
        replay.replay(snap, [ev])
        self.assertEqual(snap["artifactState"], [])
        self.assertEqual(snap["eventSequence"], 0)

    def test_bumps_event_sequence(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        ev1 = replay.EventLogEntry(eventSequence=5, outcomeId="o1", timestamp="t")
        ev2 = replay.EventLogEntry(eventSequence=10, outcomeId="o2", timestamp="t")
        result = replay.replay(snap, [ev1, ev2])
        self.assertEqual(result.final_snapshot["eventSequence"], 10)

    def test_run_id_override(self):
        snap = replay.make_initial_snapshot(runId="orig", sceneId="s1")
        result = replay.replay(snap, [], runId="override")
        self.assertEqual(result.runId, "override")
        self.assertEqual(result.final_snapshot["runId"], "override")

    def test_summary_counts(self):
        snap = replay.make_initial_snapshot(runId="r1", sceneId="s1")
        ev = replay.EventLogEntry(
            eventSequence=1, outcomeId="o1", timestamp="t",
            artifact_updates=[{"artifactId": "a", "newOwnerId": "x"}],
            event_log=[{"eventId": "e1", "description": "d"}],
            causal_seeds=[{"seedId": "s1", "planted": True}],
        )
        result = replay.replay(snap, [ev])
        self.assertEqual(result.summary["events_applied"], 1)
        self.assertEqual(result.summary["artifacts"], 1)
        self.assertEqual(result.summary["causal_seeds"], 1)
        self.assertEqual(result.summary["event_log"], 1)


class TestEventLogIO(unittest.TestCase):

    def test_load_event_log_json(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8",
        ) as fp:
            json.dump([
                {"eventSequence": 1, "outcomeId": "o1", "timestamp": "t"},
                {"eventSequence": 2, "outcomeId": "o2", "timestamp": "t"},
            ], fp)
            path = fp.name
        try:
            entries = replay.load_event_log(path)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].eventSequence, 1)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_event_log_yaml(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", delete=False, encoding="utf-8",
        ) as fp:
            fp.write("""
- eventSequence: 1
  outcomeId: o1
  timestamp: t
- eventSequence: 2
  outcomeId: o2
  timestamp: t
""")
            path = fp.name
        try:
            entries = replay.load_event_log(path)
            self.assertEqual(len(entries), 2)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_event_log_with_events_key(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8",
        ) as fp:
            json.dump({"events": [{"eventSequence": 1, "outcomeId": "o1", "timestamp": "t"}]}, fp)
            path = fp.name
        try:
            entries = replay.load_event_log(path)
            self.assertEqual(len(entries), 1)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_load_event_log_rejects_non_list(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8",
        ) as fp:
            fp.write('{"foo": "bar"}')
            path = fp.name
        try:
            with self.assertRaises(ValueError):
                replay.load_event_log(path)
        finally:
            Path(path).unlink(missing_ok=True)


class TestReplayCli(unittest.TestCase):

    def _write_event_log(self, suffix=".json") -> str:
        with tempfile.NamedTemporaryFile(
            "w", suffix=suffix, delete=False, encoding="utf-8",
        ) as fp:
            json.dump([
                {"eventSequence": 1, "outcomeId": "o1", "timestamp": "t",
                 "sceneId": "photo_lab_2008", "actionType": "give",
                 "artifact_updates": [{"artifactId": "a", "newOwnerId": "x"}],
                 "turn_index": 1},
                {"eventSequence": 2, "outcomeId": "o2", "timestamp": "t",
                 "sceneId": "photo_lab_2008", "actionType": "leave",
                 "turn_index": 2},
            ], fp)
            return fp.name

    def test_cli_with_synthetic_snapshot(self):
        cli = _load_cli_module()
        events_path = self._write_event_log()
        out_path = events_path + ".out.json"
        try:
            rc = cli.main([
                "--events", events_path,
                "--run-id", "test1",
                "--output", out_path,
            ])
            self.assertEqual(rc, 0)
            payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["runId"], "test1")
        finally:
            Path(events_path).unlink(missing_ok=True)
            Path(out_path).unlink(missing_ok=True)

    def test_cli_with_output_file(self):
        cli = _load_cli_module()
        events_path = self._write_event_log()
        out_path = events_path + ".out.json"
        try:
            rc = cli.main([
                "--events", events_path,
                "--output", out_path,
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(Path(out_path).is_file())
            payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
            self.assertIn("final_snapshot", payload)
        finally:
            Path(events_path).unlink(missing_ok=True)
            Path(out_path).unlink(missing_ok=True)

    def test_cli_with_guard_decoration(self):
        cli = _load_cli_module()
        events_path = self._write_event_log()
        out_path = events_path + ".out.json"
        try:
            rc = cli.main([
                "--events", events_path,
                "--output", out_path,
                "--guard",
            ])
            self.assertEqual(rc, 0)
            payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
            # guard: should appear in trace.applied
            all_applied = []
            for tr in payload["trace"]:
                all_applied.extend(tr.get("applied", []))
            self.assertTrue(any(a.startswith("guard:") for a in all_applied),
                            msg=f"guard marker missing: {all_applied}")
        finally:
            Path(events_path).unlink(missing_ok=True)
            Path(out_path).unlink(missing_ok=True)

    def test_cli_missing_file_returns_nonzero(self):
        cli = _load_cli_module()
        rc = cli.main(["--events", "/no/such/file.yaml"])
        self.assertEqual(rc, 1)

    def test_cli_with_snapshot(self):
        cli = _load_cli_module()
        events_path = self._write_event_log()
        # Write a tiny snapshot to a tmp file.
        import tempfile
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8",
        ) as fp:
            json.dump({
                "runId": "snap-test",
                "eventSequence": 0,
                "canonicalState": {"currentSceneId": "s1", "era": "present", "turnIndex": 0, "phase": "setup"},
                "relationshipState": [],
                "artifactState": [],
                "directorState": {"currentBeatId": "b", "elapsedTurnsInScene": 0, "actionsSpentInScene": 0},
                "beliefMatrices": [],
                "memories": [],
                "causalSeedsActive": [],
                "timestamp": "",
                "checksum": "0" * 64,
                "schemaVersion": "1.0.0",
            }, fp)
            snap_path = fp.name
        out_path = events_path + ".out.json"
        try:
            rc = cli.main([
                "--snapshot", snap_path,
                "--events", events_path,
                "--output", out_path,
            ])
            self.assertEqual(rc, 0)
            payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["runId"], "snap-test")
        finally:
            Path(events_path).unlink(missing_ok=True)
            Path(snap_path).unlink(missing_ok=True)
            Path(out_path).unlink(missing_ok=True)

    def test_cli_human_output(self):
        cli = _load_cli_module()
        events_path = self._write_event_log()
        out_path = events_path + ".out.json"
        try:
            import io
            from contextlib import redirect_stderr
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cli.main([
                    "--events", events_path,
                    "--output", out_path,
                    "--human",
                ])
            self.assertEqual(rc, 0)
            text = err.getvalue()
            self.assertIn("photo_lab_2008", text)
            self.assertIn("Replay for runId=", text)
        finally:
            Path(events_path).unlink(missing_ok=True)
            Path(out_path).unlink(missing_ok=True)

    def test_cli_stdin_events(self):
        """Feed a JSON event list via stdin and verify the CLI parses it."""
        cli = _load_cli_module()
        events = json.dumps([
            {"eventSequence": 1, "outcomeId": "o1", "timestamp": "t",
             "sceneId": "s1", "actionType": "give"},
        ])
        import io
        saved_stdin = sys.stdin
        sys.stdin = io.StringIO(events)
        out_path = tempfile.mktemp(suffix=".json")
        try:
            rc = cli.main(["--events", "-", "--output", out_path])
            self.assertEqual(rc, 0)
            payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["events_applied"], 1)
        finally:
            sys.stdin = saved_stdin
            Path(out_path).unlink(missing_ok=True)

    def test_cli_stdin_yaml_events(self):
        """YAML over stdin also works."""
        cli = _load_cli_module()
        events_yaml = """
- eventSequence: 1
  outcomeId: o1
  timestamp: t
"""
        import io
        saved_stdin = sys.stdin
        sys.stdin = io.StringIO(events_yaml)
        out_path = tempfile.mktemp(suffix=".json")
        try:
            rc = cli.main(["--events", "-", "--output", out_path])
            self.assertEqual(rc, 0)
            payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["events_applied"], 1)
        finally:
            sys.stdin = saved_stdin
            Path(out_path).unlink(missing_ok=True)

    def test_cli_stdin_empty_raises(self):
        cli = _load_cli_module()
        import io
        saved_stdin = sys.stdin
        sys.stdin = io.StringIO("")
        try:
            with self.assertRaises(SystemExit):
                cli.main(["--events", "-"])
        finally:
            sys.stdin = saved_stdin

    def test_cli_stdin_non_list_raises(self):
        cli = _load_cli_module()
        import io
        saved_stdin = sys.stdin
        sys.stdin = io.StringIO('{"foo": "bar"}')
        try:
            with self.assertRaises(SystemExit):
                cli.main(["--events", "-"])
        finally:
            sys.stdin = saved_stdin


class TestReplayWeb(unittest.TestCase):
    """Smoke tests for the replay-lab web API."""

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient  # noqa
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("fastapi not installed")
        module = _load_web_module()
        if module.app is None:  # pragma: no cover
            raise unittest.SkipTest("FastAPI app not initialised")
        cls.client = TestClient(module.app)
        cls.app = module.app

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_replay_with_synthetic_snapshot(self):
        r = self.client.post("/api/replay", json={
            "events": [
                {"eventSequence": 1, "outcomeId": "o1", "timestamp": "t",
                 "sceneId": "s1", "actionType": "give",
                 "artifact_updates": [{"artifactId": "a", "newOwnerId": "x"}],
                 "turn_index": 1},
            ],
            "run_id": "abc",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["runId"], "abc")
        self.assertEqual(body["events_applied"], 1)

    def test_replay_with_explicit_snapshot(self):
        snap = {
            "runId": "explicit",
            "eventSequence": 0,
            "canonicalState": {"currentSceneId": "s1", "era": "present", "turnIndex": 0, "phase": "setup"},
            "relationshipState": [],
            "artifactState": [{"artifactId": "x", "ownerId": "leila", "state": "init", "isRevealed": True}],
            "directorState": {"currentBeatId": "b", "elapsedTurnsInScene": 0, "actionsSpentInScene": 0},
            "beliefMatrices": [],
            "memories": [],
            "causalSeedsActive": [],
            "timestamp": "",
            "checksum": "0" * 64,
            "schemaVersion": "1.0.0",
        }
        r = self.client.post("/api/replay", json={
            "snapshot": snap,
            "events": [
                {"eventSequence": 1, "outcomeId": "o1", "timestamp": "t",
                 "artifact_updates": [{"artifactId": "x", "newOwnerId": "arash"}]},
            ],
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["final_snapshot"]["artifactState"][0]["ownerId"], "arash")

    def test_replay_empty_events_400(self):
        r = self.client.post("/api/replay", json={"events": []})
        self.assertEqual(r.status_code, 400)

    def test_replay_with_guard(self):
        r = self.client.post("/api/replay", json={
            "events": [
                {"eventSequence": 1, "outcomeId": "o1", "timestamp": "t"},
            ],
            "guard": True,
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        applied = body["trace"][0]["applied"]
        self.assertTrue(any(a.startswith("guard:") for a in applied))

    def test_root_serves_ui(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        self.assertIn("replay-lab", r.text)


if __name__ == "__main__":
    unittest.main()
