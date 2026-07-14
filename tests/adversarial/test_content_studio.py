"""
test_content_studio.py
======================
Smoke + functional tests for the content-studio backend.

The tests run against the FastAPI app via ``fastapi.testclient.TestClient``,
which exercises the real ASGI stack without a network roundtrip.  This
catches route wiring errors, JSON schema drift, and the path-traversal
guard without spinning up a real server.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(_TOOLS))

from fastapi.testclient import TestClient  # noqa: E402


def _load_app():
    """Load the content-studio server module via importlib (the directory
    name contains a dash, so a normal ``import`` won't work)."""
    server_path = _TOOLS / "content-studio" / "server.py"
    spec = importlib.util.spec_from_file_location(
        "content_studio_server_for_test", server_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.app


class TestContentStudioApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(_load_app())

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("guard_version", body)

    def test_list_cases(self):
        r = self.client.get("/api/cases")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("cases", body)
        self.assertIsInstance(body["cases"], list)
        # We have at least one case (case_01_revolution_street).
        self.assertGreater(len(body["cases"]), 0)
        first = body["cases"][0]
        self.assertIn("scenes", first)
        self.assertGreater(len(first["scenes"]), 0)

    def test_get_file_real_scene(self):
        r = self.client.get(
            "/api/file",
            params={"path": "content/case_01_revolution_street/scenes/photo_lab_2008.yaml"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("text", body)
        self.assertIn("photo_lab_2008", body["text"])

    def test_get_file_404(self):
        r = self.client.get("/api/file", params={"path": "content/does_not_exist.yaml"})
        self.assertEqual(r.status_code, 404)

    def test_get_file_path_traversal_blocked(self):
        r = self.client.get("/api/file", params={"path": "../etc/passwd"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("escapes", r.json()["detail"])

    def test_guard_on_real_scene(self):
        r = self.client.post(
            "/api/guard",
            json={"path": "content/case_01_revolution_street/scenes/photo_lab_2008.yaml"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # W1-C scene contracts now declare mandatory_echoes
        # (decision-3 compliance).  The D check should pass; Q1/Q2
        # are advisory on contracts.  Therefore the contract is not
        # blocking.
        self.assertFalse(body["blocking"], msg=body)
        d = next(x for x in body["results"] if x["id"] == "D_mandatory_echo_declared")
        self.assertTrue(d["passed"], msg=f"D should pass: {d['detail']}")

    def test_guard_text_passing(self):
        yaml_text = """
sceneId: passing_test
required_anchors: []
allowed_beats: []
mandatory_echoes:
  - id: echo_a
    description: required
artifact_updates:
  - artifactId: a
    newOwnerId: leila
event_log:
  - eventId: e
    description: test
belief_updates:
  - characterId: leila
    subject: x
    belief_state: certain
    confidence: 0.9
belief_matrix:
  - characterId: leila
    addedMemory: m
turn_budget:
  total: 5
  current_turn: 2
  max_turns: 5
action_whitelist:
  - investigate
  - give
causal_seeds:
  - seedId: e1
    planted: true
far_echo_routes:
  - targetSceneId: reunion_2024
    seedIds:
      - e1
"""
        r = self.client.post(
            "/api/guard-text",
            json={"text": yaml_text, "filename": "test.yaml"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["blocking"], msg=json.dumps(body, ensure_ascii=False))

    def test_guard_text_blocking(self):
        yaml_text = """
sceneId: blocking_test
required_anchors: []
allowed_beats: []
artifact_updates: []
event_log: []
belief_updates: []
belief_matrix: []
"""
        r = self.client.post(
            "/api/guard-text",
            json={"text": yaml_text, "filename": "test.yaml"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # Scene contract without mandatory_echoes → D blocks
        self.assertTrue(body["blocking"])
        self.assertTrue(any("D_" in r for r in body["blocking_reasons"]))

    def test_guard_text_yaml_parse_error(self):
        r = self.client.post(
            "/api/guard-text",
            json={"text": "this is: not: valid: yaml: at all", "filename": "bad.yaml"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["blocking"])
        self.assertTrue(any("YAML parse error" in r for r in body["blocking_reasons"]))

    def test_guard_text_not_a_mapping(self):
        r = self.client.post(
            "/api/guard-text",
            json={"text": "- one\n- two\n- three", "filename": "list.yaml"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["blocking"])
        self.assertTrue(any("mapping" in r for r in body["blocking_reasons"]))

    def test_save_round_trip(self):
        # Save a known-good scene contract to a tmp file under content/
        # and verify the guard result is returned alongside the save.
        import tempfile
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", delete=False, encoding="utf-8",
            dir=str(_TOOLS.parent / "content" / "case_01_revolution_street" / "scenes"),
        ) as fp:
            fp.write("""# smoke test fixture
sceneId: __smoke_test__
required_anchors: []
allowed_beats: []
mandatory_echoes:
  - id: echo_a
    description: required
""")
            path = fp.name
        relpath = "content/case_01_revolution_street/scenes/" + Path(path).name
        try:
            r = self.client.post(
                "/api/save",
                json={
                    "path": relpath,
                    "text": "sceneId: __smoke_test__\nrequired_anchors: []\nallowed_beats: []\nmandatory_echoes:\n  - id: echo_a\n    description: required\n",
                },
            )
            self.assertEqual(r.status_code, 200, msg=r.text)
            body = r.json()
            self.assertTrue(body["saved"])
            self.assertIn("guard", body)
            self.assertFalse(body["guard"]["blocking"])
        finally:
            Path(path).unlink(missing_ok=True)

    def test_save_yaml_error_returns_400(self):
        r = self.client.post(
            "/api/save",
            json={"path": "content/x.yaml", "text": "this is: not: yaml"},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("YAML parse error", r.json()["detail"])

    def test_save_path_traversal_blocked(self):
        r = self.client.post(
            "/api/save",
            json={"path": "../escape.yaml", "text": "sceneId: x"},
        )
        self.assertEqual(r.status_code, 400)

    def test_root_serves_ui(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))
        # The UI is wired to /api/* endpoints — verify some key strings.
        self.assertIn("content-studio", r.text)
        self.assertIn("/api/guard-text", r.text)


if __name__ == "__main__":
    unittest.main()
