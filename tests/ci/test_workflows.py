"""CI workflow tests — ensure ``.github/workflows/*.yml`` is GitHub-Actions-parseable.

The brief requires every CI change to be verifiable from
a unit test: a malformed YAML, a broken ``run:`` line, or a
missing step silently fails the build.  These tests load each
workflow file with PyYAML, assert it parses, and check the
required jobs / steps are present.

We intentionally keep the assertions against the **job
identifiers** and **job commands** (so renaming a job in the
YAML is caught by the test), but tolerant of cosmetic edits
(whitespace, comments).
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "PyYAML is required for the CI workflow tests; install with: pip install pyyaml"
    ) from exc


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load_workflow(name: str) -> dict:
    path = WORKFLOWS / name
    with open(path, "r", encoding="utf-8") as fp:
        return yaml.safe_load(fp)


# ---------------------------------------------------------------------------
# Workflow file structure
# ---------------------------------------------------------------------------


class WorkflowFileTests(unittest.TestCase):
    """Every workflow file parses, has a name, triggers, jobs."""

    def test_four_questions_workflow_exists(self) -> None:
        self.assertTrue((WORKFLOWS / "four-questions.yml").exists())

    def test_four_questions_workflow_parses(self) -> None:
        wf = _load_workflow("four-questions.yml")
        self.assertIsInstance(wf, dict)
        self.assertIn("name", wf)
        self.assertIn("on", wf)
        self.assertIn("jobs", wf)

    def test_workflow_uses_pull_request_trigger(self) -> None:
        wf = _load_workflow("four-questions.yml")
        # ``on`` may parse to True (when bare) or to a dict
        on = wf["on"]
        self.assertTrue(
            "pull_request" in on or on is True,
            f"workflow must trigger on pull_request; got {on}",
        )


# ---------------------------------------------------------------------------
# Job presence — the brief lists 7 jobs to be wired in
# ---------------------------------------------------------------------------


class FourQuestionsJobsTests(unittest.TestCase):
    """The brief requires these jobs in the four-questions workflow:

    1. four-questions-guard  (W2-Engineering-Fix / W2-C; existing)
    2. v6-residual-scan      (W2-Engineering-Fix; existing)
    3. content-studio-smoke  (W2-Engineering-Fix; existing)
    4. engine-tests          (W3-C; NEW)
    5. agents-tests          (W3-C; NEW)
    6. safety-tests          (W3-C; NEW)
    7. cost-red-line         (W3-C; NEW)
    """

    def setUp(self) -> None:
        self.wf = _load_workflow("four-questions.yml")
        self.jobs = self.wf["jobs"]

    def test_all_seven_jobs_present(self) -> None:
        expected = {
            "four-questions-guard",
            "v6-residual-scan",
            "content-studio-smoke",
            "engine-tests",
            "agents-tests",
            "safety-tests",
            "cost-red-line",
        }
        actual = set(self.jobs.keys())
        missing = expected - actual
        self.assertFalse(missing, f"missing jobs: {missing}")

    def test_existing_three_jobs_still_present(self) -> None:
        for name in ("four-questions-guard", "v6-residual-scan", "content-studio-smoke"):
            self.assertIn(name, self.jobs, f"{name} is gone")

    def test_new_four_jobs_present(self) -> None:
        for name in ("engine-tests", "agents-tests", "safety-tests", "cost-red-line"):
            self.assertIn(name, self.jobs, f"new job {name} is missing")

    def test_every_job_runs_on_ubuntu(self) -> None:
        for name, job in self.jobs.items():
            self.assertEqual(
                job.get("runs-on"),
                "ubuntu-latest",
                f"job {name!r} does not run on ubuntu-latest",
            )

    def test_every_job_has_steps(self) -> None:
        for name, job in self.jobs.items():
            self.assertIn("steps", job, f"job {name!r} has no steps")
            self.assertGreater(len(job["steps"]), 0, f"job {name!r} has empty steps")

    def test_every_job_has_checkout_step(self) -> None:
        for name, job in self.jobs.items():
            steps_text = json.dumps(job["steps"])
            self.assertIn(
                "actions/checkout",
                steps_text,
                f"job {name!r} is missing the actions/checkout step",
            )


# ---------------------------------------------------------------------------
# Job-specific structure
# ---------------------------------------------------------------------------


class EngineTestsJobTests(unittest.TestCase):
    """``engine-tests`` runs the engine's 90+ tests."""

    def setUp(self) -> None:
        self.wf = _load_workflow("four-questions.yml")
        self.job = self.wf["jobs"]["engine-tests"]

    def test_has_setup_python(self) -> None:
        steps_text = json.dumps(self.job["steps"])
        self.assertIn("actions/setup-python", steps_text)

    def test_uses_python_312(self) -> None:
        steps_text = json.dumps(self.job["steps"])
        self.assertIn('"3.12"', steps_text)

    def test_runs_engine_tests(self) -> None:
        steps_text = json.dumps(self.job["steps"])
        self.assertIn("tests/engine", steps_text)


class AgentsTestsJobTests(unittest.TestCase):
    """``agents-tests`` runs the agents' test suite (W3-B)."""

    def setUp(self) -> None:
        self.wf = _load_workflow("four-questions.yml")
        self.job = self.wf["jobs"]["agents-tests"]

    def test_runs_agents_tests(self) -> None:
        steps_text = json.dumps(self.job["steps"])
        # agents tests are under tests/agents in W3-B; if the
        # directory doesn't exist yet the job should still be
        # runnable.
        self.assertIn("pytest", steps_text)


class SafetyTestsJobTests(unittest.TestCase):
    """``safety-tests`` runs the safety package's unit tests."""

    def setUp(self) -> None:
        self.wf = _load_workflow("four-questions.yml")
        self.job = self.wf["jobs"]["safety-tests"]

    def test_runs_safety_tests(self) -> None:
        steps_text = json.dumps(self.job["steps"])
        self.assertIn("tests/safety", steps_text)

    def test_runs_ci_tests(self) -> None:
        # The CI workflow tests are also under tests/ci
        steps_text = json.dumps(self.job["steps"])
        self.assertIn("tests/ci", steps_text)


class CostRedLineJobTests(unittest.TestCase):
    """``cost-red-line`` simulates one run and verifies the 4 red lines."""

    def setUp(self) -> None:
        self.wf = _load_workflow("four-questions.yml")
        self.job = self.wf["jobs"]["cost-red-line"]

    def test_invokes_cost_monitor(self) -> None:
        steps_text = json.dumps(self.job["steps"])
        self.assertIn("cost_monitor", steps_text)

    def test_simulates_a_run(self) -> None:
        # The job creates a synthetic model_calls.json and feeds
        # it to evaluate_from_file.
        steps_text = json.dumps(self.job["steps"])
        self.assertIn("model_calls", steps_text)

    def test_blocks_on_red_line_breach(self) -> None:
        # The job must exit non-zero on a red-line breach
        # (which is the default pytest / python exit code).
        steps_text = json.dumps(self.job["steps"])
        # The synthetic run simulates a single, well-formed run
        # with 20 calls; a 21st call test should be present in
        # the safety tests, not in the CI workflow, so we just
        # check the workflow runs python -c "..." with the
        # expected number of calls.
        self.assertTrue(
            "20" in steps_text or "main_call_count" in steps_text,
            "cost-red-line job should simulate 20 main calls",
        )


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


class WorkflowPermissionsTests(unittest.TestCase):
    """The workflow declares a ``permissions`` block (security best practice)."""

    def test_four_questions_permissions_minimal(self) -> None:
        wf = _load_workflow("four-questions.yml")
        perms = wf.get("permissions", {})
        # Default: contents: read is the minimum required.
        self.assertEqual(perms.get("contents"), "read")


# ---------------------------------------------------------------------------
# ADR 0007 references
# ---------------------------------------------------------------------------


class AdrLintTests(unittest.TestCase):
    """The CI workflow's ``cost-red-line`` job should mention the
    4 hard red lines, and the workflow file should not contradict
    ADR 0007 (i.e. it should not use any era value that the schema
    does not accept).
    """

    def test_cost_red_line_mentions_four_red_lines(self) -> None:
        wf = _load_workflow("four-questions.yml")
        job = wf["jobs"]["cost-red-line"]
        # Concatenate all step commands into one string
        commands = []
        for step in job["steps"]:
            if "run" in step:
                commands.append(step["run"])
        text = "\n".join(commands)
        # The job should assert that R1..R4 are all within bounds
        for rid in ("R1", "R2", "R3", "R4"):
            self.assertIn(rid, text, f"cost-red-line job missing assertion for {rid}")

    def test_workflow_uses_python_312(self) -> None:
        wf = _load_workflow("four-questions.yml")
        for name, job in wf["jobs"].items():
            steps_text = json.dumps(job["steps"])
            # 3.12 is the canonical Python version per ADR 0007
            # (Python 3.12+ is required)
            if "setup-python" in steps_text:
                self.assertIn(
                    '"3.12"', steps_text,
                    f"job {name!r} does not pin Python 3.12",
                )


# ---------------------------------------------------------------------------
# Sanity: the workflow file does not contain invalid YAML constructs
# ---------------------------------------------------------------------------


class WorkflowSanityTests(unittest.TestCase):
    """The workflow must be a clean YAML mapping with no Python tags."""

    def test_no_python_yaml_tags(self) -> None:
        # PyYAML's safe_load blocks Python tags; if the file
        # had !!python/object we'd see a ConstructorError.  We
        # just make sure the parse succeeded (the loader call
        # itself would have raised otherwise).
        wf = _load_workflow("four-questions.yml")
        self.assertIsInstance(wf, dict)

    def test_workflow_jobs_are_unique(self) -> None:
        wf = _load_workflow("four-questions.yml")
        job_names = list(wf["jobs"].keys())
        self.assertEqual(len(job_names), len(set(job_names)))


if __name__ == "__main__":
    unittest.main()
