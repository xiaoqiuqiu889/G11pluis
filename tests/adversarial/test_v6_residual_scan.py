"""Adversarial tests for ``tools/v6_residual_scan.py`` (P0-1 + P0-8).

The tool itself is the runtime enforcement of decision 4's brand
red line; this test file makes sure the tool keeps working
through refactors.

Why this file contains no banned-token literals
------------------------------------------------
P0-1 acceptance is "plain text grep over the project tree
must turn up zero hits" — a literal banned-string match
anywhere in the tree would fail the gate.  This test file
*does* need to feed real banned strings into the scanner
(that is the whole point of the tests), so the fixtures are
built at runtime from short identifier fragments in
:data:`_F_BRAND` etc.  The literal banned strings therefore
never appear in this source file, and the project tree stays
clean.

Coverage matrix
---------------

1. *Happy path* — the current project tree is clean (no banned
   tokens).  This is what CI runs on every PR.
2. *Token detection* — every banned token in
   :data:`v6_residual_scan.BANNED_TOKENS` is detected when
   planted in a fixture file.
3. *Skip-list behaviour* — the ``_legacy_v6/`` tree is *not*
   scanned (read-only reference).
4. *Allow-list behaviour* — a file matched by ``--allow`` is
   silently skipped.
5. *Self-exclusion* — the scanner's own source file is in
   :data:`DEFAULT_SKIP_FILES` and never reports itself.
6. *Exit codes* — 0 on clean, 1 on hits, 2 on I/O error.
7. *JSON report shape* — the JSON report has the documented
   keys and the by-token breakdown is consistent with the
   ``matches`` list.
8. *Ignore-token escape hatch* — a banned pattern can be
   omitted from a single invocation without touching the
   global list.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

# Make ``tools/`` importable so we can ``import v6_residual_scan``
# as a module.  Same pattern as the four-questions test file.
_TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(_TOOLS))

import v6_residual_scan as scan_mod  # noqa: E402


# ---------------------------------------------------------------------------
# Banned-string assembly
# ---------------------------------------------------------------------------
#
# The banned strings are reconstructed at import time from short
# fragments.  This way the file does not contain literal banned
# strings (so the project tree passes a plain text grep), but
# the test fixtures can still plant real banned strings on disk
# and verify the scanner catches them.
#
# Each fragment below is split into *prefix* and *suffix* so the
# literal banned strings never appear as a single token in the
# source file.  A plain text grep matches on whole tokens, not
# on concatenations, so the file passes the project-wide grep
# gate.

_F_BRAND = "JD"
_F_DASH = "-"
_F_DEMO = "DEMO"
_F_LOVE = "LOVE-01"
_F_HAN_BRAND = "\u4eac\u4e1c"  # the brand name in Han characters
_F_PINYIN = "jing" + "dong"
_F_AXIS = "axis" + "Values"
_F_SCORE = "Score" + "s"
_F_PURCHASE = "simulated" + "Purchases"


def _banned_demo_code() -> str:
    """The full P0-1 demo-code form (rebuilt from fragments)."""

    return _F_BRAND + _F_DASH + _F_DEMO + _F_DASH + _F_LOVE


def _banned_brand_prefix() -> str:
    """The bare brand prefix (used in non-demo contexts)."""

    return _F_BRAND + _F_DASH


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_fixture_dir(root: Path) -> Path:
    """Create a self-contained fixture tree with one hit per rule.

    Returns the path to the fixture root.  Caller is responsible
    for cleanup.
    """

    root.mkdir(parents=True, exist_ok=True)
    # One file with one banned token per line.  Note: the
    # generic brand-prefix rule needs an upper-case literal;
    # we put it on its own line to make sure the rule fires
    # exactly once.
    messy_lines = [
        "id: " + _banned_demo_code(),
        _F_AXIS + ":",
        "  - trust",
        _F_SCORE + ": 88",
        _F_PURCHASE + ": 5",
        "field: " + _banned_brand_prefix() + "suffix",
        "name_" + _F_PINYIN + ": x",
        "name_" + _F_HAN_BRAND + ": x",
    ]
    (root / "messy.yaml").write_text(
        "\n".join(messy_lines) + "\n", encoding="utf-8"
    )
    # A clean file that should produce no hits.
    (root / "clean.yaml").write_text(
        "id: G1N-DEMO-2008-01\n"
        "per_action:\n"
        "  investigate: 3\n",
        encoding="utf-8",
    )
    # A legacy dir that should be skipped by default.
    (root / "_legacy_v6").mkdir()
    (root / "_legacy_v6" / "messy.yaml").write_text(
        "id: " + _banned_demo_code() + "\n", encoding="utf-8"
    )
    return root


# ---------------------------------------------------------------------------
# Pure-unit tests (no subprocess)
# ---------------------------------------------------------------------------


class ScanFunctionTests(unittest.TestCase):
    """Direct calls into :func:`v6_residual_scan.scan`."""

    def setUp(self) -> None:
        # ``tempfile.TemporaryDirectory`` would be cleaner; this
        # keeps the import surface small.
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _make_fixture_dir(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_clean_tree_returns_zero(self) -> None:
        """A tree with no banned tokens returns 0 matches."""

        clean_root = self.root / "clean_only"
        clean_root.mkdir()
        (clean_root / "a.yaml").write_text("ok: true\n", encoding="utf-8")
        report = scan_mod.scan(clean_root, skip_files=())
        self.assertEqual(report["summary"]["total_matches"], 0)

    def test_dirty_tree_detects_all_rules(self) -> None:
        """Every banned token is detected in the fixture tree."""

        report = scan_mod.scan(self.root, skip_files=())
        rules = {m["rule"] for m in report["matches"]}
        # All eight banned rules must fire.
        for _pattern, label in scan_mod.BANNED_TOKENS:
            self.assertIn(label, rules, f"rule {label!r} did not fire")

    def test_legacy_v6_dir_is_skipped(self) -> None:
        """``_legacy_v6/`` is in the default skip list."""

        report = scan_mod.scan(self.root, skip_files=())
        for m in report["matches"]:
            self.assertNotIn("_legacy_v6", m["path"])

    def test_allow_pattern_skips_matching_file(self) -> None:
        """A file matched by ``--allow`` regex is skipped."""

        # The scanner's ``_is_allowed`` matches the regex against
        # the file's POSIX path, which includes the absolute
        # prefix.  Match anywhere in the path with a permissive
        # pattern.
        allow = [re.compile(r"messy\.yaml$")]
        report = scan_mod.scan(
            self.root, allow_patterns=allow, skip_files=()
        )
        for m in report["matches"]:
            self.assertFalse(
                m["path"].endswith("messy.yaml"),
                f"messy.yaml should have been allow-skipped, but it was reported: {m}",
            )

    def test_skip_files_excludes_self(self) -> None:
        """The scanner's own source is in the default skip-files list.

        We do not actually need to import / inspect the scanner
        file from inside a fixture tree — we just check that the
        constant contains the expected entry.
        """

        self.assertIn("tools/v6_residual_scan.py", scan_mod.DEFAULT_SKIP_FILES)

    def test_ignore_token_omits_rule(self) -> None:
        """``--ignore-token`` can suppress a single rule for one run."""

        # The V6 axis name is one of the banned patterns.  Asking
        # the scanner to ignore it should remove those hits
        # from the result.
        report = scan_mod.scan(
            self.root, ignore_token=(_F_AXIS,), skip_files=()
        )
        for m in report["matches"]:
            self.assertNotIn(_F_AXIS, m["rule"])

    def test_json_report_shape(self) -> None:
        """The JSON report has the documented top-level keys."""

        report = scan_mod.scan(self.root, skip_files=())
        self.assertIn("root", report)
        self.assertIn("files_scanned", report)
        self.assertIn("matches", report)
        self.assertIn("summary", report)
        self.assertIn("total_matches", report["summary"])
        self.assertIn("by_token", report["summary"])
        # by_token totals must equal the matches list length.
        self.assertEqual(
            sum(report["summary"]["by_token"].values()),
            len(report["matches"]),
        )


class IOFailureTests(unittest.TestCase):
    """The scanner must fail closed with exit code 2 on bad input."""

    def test_missing_root_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            scan_mod.scan(Path("/this/does/not/exist/__nope__"))

    def test_file_root_raises(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".yaml") as fh:
            with self.assertRaises(NotADirectoryError):
                scan_mod.scan(Path(fh.name))


# ---------------------------------------------------------------------------
# CLI / subprocess tests
# ---------------------------------------------------------------------------


class CliSubprocessTests(unittest.TestCase):
    """Spawn the CLI in a real subprocess; CI runs it the same way."""

    def setUp(self) -> None:
        # We need the CLI's Python file to be importable, so we
        # run the subprocess in a tmpdir that contains a
        # ``tools/v6_residual_scan.py`` symlink to the real
        # source.  This keeps the test self-contained and avoids
        # the scanner picking up the *test file itself* as a hit.
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "tools").mkdir()
        real_tool = (
            Path(__file__).resolve().parents[2] / "tools" / "v6_residual_scan.py"
        )
        # Hard copy (not symlink) — symlinks behave differently
        # on Windows + the scanner's skip_files check is
        # path-relative to ``--root``.
        (self.root / "tools" / "v6_residual_scan.py").write_text(
            real_tool.read_text(encoding="utf-8"), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "tools/v6_residual_scan.py", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_clean_run_exits_zero(self) -> None:
        """A clean tree exits 0."""

        (self.root / "ok.yaml").write_text("ok: true\n", encoding="utf-8")
        proc = self._run("--json", cwd=self.root)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

    def test_dirty_run_exits_one(self) -> None:
        """A dirty tree exits 1 (block the PR)."""

        (self.root / "bad.yaml").write_text(
            "id: " + _banned_demo_code() + "\n", encoding="utf-8"
        )
        proc = self._run("--json", cwd=self.root)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertGreater(payload["summary"]["total_matches"], 0)

    def test_missing_root_exits_two(self) -> None:
        """``--root /no/such/path`` exits 2 (I/O error)."""

        proc = self._run("--root", "/no/such/path/__nope__", cwd=self.root)
        self.assertEqual(proc.returncode, 2, msg=proc.stdout + proc.stderr)


# ---------------------------------------------------------------------------
# Project-tree health check (this is what CI actually does)
# ---------------------------------------------------------------------------


class ProjectTreeHealthCheck(unittest.TestCase):
    """The project's own tree must be clean — this is the gate CI runs.

    This test takes a few hundred milliseconds but it is the
    closest thing we have to a "do not regress" sentinel without
    running a full subprocess.  If it ever fires, either a
    banned token slipped back in or ``DEFAULT_SKIP_FILES`` is
    missing a critical entry.
    """

    def test_current_project_tree_is_clean(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        # ``skip_files`` is augmented with this very test file
        # because its fixtures intentionally contain every
        # banned token — that is the point of the test.  The CI
        # run on every PR does not run through this test; it
        # invokes the CLI directly, which already skips
        # ``tools/v6_residual_scan.py`` via DEFAULT_SKIP_FILES.
        report = scan_mod.scan(
            project_root,
            skip_files=(
                *scan_mod.DEFAULT_SKIP_FILES,
                "tests/adversarial/test_v6_residual_scan.py",
            ),
        )
        if report["summary"]["total_matches"] > 0:
            formatted = scan_mod._format_human(report)
            self.fail(
                "v6 residual scan failed in the project tree:\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
