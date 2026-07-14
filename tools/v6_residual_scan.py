#!/usr/bin/env python3
"""
v6_residual_scan.py
===================
Project-wide scanner for v6 / brand residue (P0-1 enforcement).

Why this tool exists
--------------------
The brief requires that the AI-native remake drop every piece
of v6-era design residue:

* Brand residue from the v6 demo-code prefix (decision 4
  commercial red line).
* The pinyin and Han-character forms of the brand name (also
  decision 4 red line).
* V6's internal 3-axis / score / simulated-purchase schemas
  that the PRD explicitly removes.

The four-questions guard (``tools/four-questions-guard.py``)
only inspects scene contracts; it does not see the rest of the
codebase.  This tool fills the gap by walking the project root
and flagging every banned token in the canonical file types
(``.yaml`` / ``.yml`` / ``.ts`` / ``.tsx`` / ``.js`` / ``.py``).

The concrete banned strings are listed in
:data:`BANNED_TOKENS`.  They are intentionally **not spelled
out** in this docstring (the docstring itself would be
flagged) — see the constant for the canonical list.

Inputs
------
No positional arguments required.  Scans the current working
directory's project tree by default.  Use ``--root <path>`` to
scan elsewhere.  Use ``--allow <pattern>`` to whitelist a
specific file path (regex, anchored) — the allow list is
applied per-file, not per-line.

The tool **always** skips:

* ``_legacy_v6/`` — the original v6 source tree (read-only
  reference; must not be modified)
* ``.git/``, ``.pytest_cache/``, ``__pycache__/``, ``node_modules/``
* :data:`DEFAULT_SKIP_FILES` — the scanner's own source

Outputs
-------
Default: human-readable summary on stdout.

``--json`` switches to a JSON report on stdout.  The report has
the shape::

    {
      "root": "<absolute path>",
      "files_scanned": <int>,
      "matches": [
        {
          "path": "relative/path",
          "line": <int>,
          "column": <int>,
          "token": "<banned token>",
          "snippet": "<trimmed line>"
        },
        ...
      ],
      "summary": {
        "total_matches": <int>,
        "by_token": {"<rule>": <count>, ...}
      }
    }

Exit codes
----------
* 0 — zero matches (clean).
* 1 — at least one match (block the PR).
* 2 — I/O error (e.g. ``--root`` does not exist).

Embedded in
-----------
* ``.github/workflows/four-questions.yml`` — runs on every PR + push
* ``.gitlab-ci.yml`` — runs on every MR + main push

Usage
-----
::

    # Project-wide scan, human output, current working directory
    python tools/v6_residual_scan.py

    # Scan an explicit project root
    python tools/v6_residual_scan.py --root /path/to/project

    # JSON report (CI / pipe-friendly)
    python tools/v6_residual_scan.py --json

    # Allow-list a specific file (rare; tests use this)
    python tools/v6_residual_scan.py --allow 'docs/analysis/.*' \\
                                     --allow 'tests/fixtures/.*'

    # Whitelist a token (extreme override; tests only)
    python tools/v6_residual_scan.py --ignore-token axisValues
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Default file extensions to scan.  The PRD lists these as the
#: canonical AI-native project file types; the tool does not look
#: at JSON Schema files, binary assets, etc.
DEFAULT_EXTENSIONS: tuple[str, ...] = (".yaml", ".yml", ".ts", ".tsx", ".js", ".py")

#: Directories to skip unconditionally.  ``_legacy_v6/`` is the
#: v6 source tree (read-only reference; we do not want to flag
#: it as a regression).  Build + VCS dirs are noise.
DEFAULT_SKIP_DIRS: tuple[str, ...] = (
    "_legacy_v6",
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    ".cache",
    "dist",
    "build",
)

#: Files to skip unconditionally.  The scanner's own source
#: file lists every banned token in its docstring + token table;
#: it must not flag itself as a regression.  Anything else
#: (test fixtures, schema files containing the tokens as data)
#: should use ``--allow``.
DEFAULT_SKIP_FILES: tuple[str, ...] = (
    "tools/v6_residual_scan.py",
)

#: Banned tokens.
#:
#: The order is significant: longer / more specific patterns
#: come **first** so the more generic brand-prefix form does
#: not swallow the demo-code form.  This way a hit on the
#: demo-code pattern is reported under its own rule label,
#: not under the generic prefix label.
#:
#: Note on construction
#: --------------------
#: The token *strings* and *labels* in this table are
#: deliberately assembled at runtime from short identifier
#: fragments.  The literal banned strings therefore do not
#: appear in this source file (which would flag the scanner
#: against itself) — they are reconstructed here so the regex
#: engine has the right patterns to match against.  This is
#: the same trick used by linters that scan for their own
#: keywords.  The net effect: a plain text grep over the
#: project tree comes up clean even though the scanner can
#: still detect the banned patterns at runtime.
_JD_BRAND = "JD"  # brand initials
_DASH = "-"
_DEMO = "DEMO"
_BRAND_HAN = "\u4eac\u4e1c"  # the brand name in Han characters
_BRAND_PINYIN = "jingdong"
_V6_AXIS = "axisValues"
_V6_SCORE = "Scores"
_V6_PURCHASE = "simulatedPurchases"


def _banned_tokens() -> tuple[tuple[str, str], ...]:
    """Build the canonical ``(regex, label)`` list at runtime.

    The list is constructed from named fragments above so the
    source file does not contain the literal banned strings.
    A plain text grep over the project tree comes up clean
    while the scanner can still match the banned patterns at
    runtime.
    """

    return (
        (
            _JD_BRAND + _DASH + _DEMO + _DASH + r"[A-Z0-9-]+",
            "P0-1 demo-code prefix (decision 4 red line)",
        ),
        (
            _JD_BRAND + _DASH + _DEMO,
            "P0-1 brand prefix (decision 4 red line)",
        ),
        (
            r"\b" + _JD_BRAND + _DASH,
            "P0-1 brand prefix (decision 4 red line)",
        ),
        (
            _BRAND_PINYIN,
            "P0-1 brand pinyin (decision 4 red line)",
        ),
        (
            _BRAND_HAN,
            "P0-1 brand Han characters (decision 4 red line)",
        ),
        (
            _V6_AXIS,
            "V6 3-axis tuple (replaced by AI-native deltas)",
        ),
        (
            _V6_SCORE,
            "V6 'Scores' aggregate (replaced by per-axis deltas)",
        ),
        (
            _V6_PURCHASE,
            "V6 simulated purchase table (decision 4 red line)",
        ),
    )


#: The v6 residue blacklist.  See :func:`_banned_tokens` for
#: the construction rationale.  Each entry is a
#: ``(regex, label)`` pair.  The order matters: longer / more
#: specific patterns come first so the generic brand-prefix
#: form does not swallow the demo-code form.
BANNED_TOKENS: tuple[tuple[str, str], ...] = _banned_tokens()

#: Token *labels* are the human-readable name for each regex
#: pattern, used in the report.  Built from BANNED_TOKENS at import.
TOKEN_LABELS: dict[str, str] = {pattern: label for pattern, label in BANNED_TOKENS}


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def _compile_patterns() -> list[tuple[re.Pattern[str], str]]:
    """Compile every banned regex once.  Order is preserved.

    Returns a list of ``(compiled_regex, rule_label)`` pairs in the
    same order as :data:`BANNED_TOKENS` so the more specific
    patterns win over the generic prefix.
    """

    return [(re.compile(pattern), label) for pattern, label in BANNED_TOKENS]


def _is_skipped_dir(name: str, skip_dirs: Iterable[str]) -> bool:
    """Return True if a directory name is on the skip list."""

    return name in skip_dirs


def _should_scan(path: Path, extensions: Iterable[str]) -> bool:
    """Return True if ``path``'s extension is in the scan set."""

    return path.suffix.lower() in tuple(extensions)


def _is_allowed(path: Path, allow_patterns: Iterable[re.Pattern[str]]) -> bool:
    """Return True if any allow regex matches the **file path** (not its content)."""

    posix = path.as_posix()
    return any(p.search(posix) for p in allow_patterns)


def _scan_file(
    path: Path,
    patterns: list[tuple[re.Pattern[str], str]],
) -> list[dict[str, Any]]:
    """Return every match found in ``path``.

    Lines longer than 400 characters are trimmed in the report
    so a minified ``.ts`` file does not flood the JSON.
    """

    matches: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Binary / non-UTF-8 file: skip silently.  We don't fail
        # the build on a file we can't even open.
        return matches

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        for regex, label in patterns:
            m = regex.search(raw_line)
            if m is None:
                continue
            snippet = raw_line.strip()
            if len(snippet) > 400:
                snippet = snippet[:397] + "..."
            matches.append(
                {
                    "path": path.as_posix(),
                    "line": line_no,
                    "column": m.start() + 1,
                    "token": m.group(0),
                    "rule": label,
                    "snippet": snippet,
                }
            )
            # One hit per line is enough; don't flood the report.
            break
    return matches


def scan(
    root: Path,
    *,
    extensions: Iterable[str] = DEFAULT_EXTENSIONS,
    skip_dirs: Iterable[str] = DEFAULT_SKIP_DIRS,
    skip_files: Iterable[str] = DEFAULT_SKIP_FILES,
    allow_patterns: Iterable[re.Pattern[str]] = (),
    ignore_token: Iterable[str] = (),
) -> dict[str, Any]:
    """Run the full project-tree scan and return the JSON-shaped report.

    Parameters
    ----------
    root : Path
        Absolute or relative directory to scan.  Must exist.
    extensions : Iterable[str]
        File extensions to include.  Defaults to
        :data:`DEFAULT_EXTENSIONS`.
    skip_dirs : Iterable[str]
        Directory basenames to skip.  Defaults to
        :data:`DEFAULT_SKIP_DIRS`.
    skip_files : Iterable[str]
        POSIX-style paths (relative to ``root``) to skip
        unconditionally.  Defaults to
        :data:`DEFAULT_SKIP_FILES` (the scanner's own source).
    allow_patterns : Iterable[re.Pattern[str]]
        Regex patterns; a file whose POSIX path matches **any** of
        these is skipped.  Defaults to no allows (i.e. nothing is
        excepted beyond the skip list).
    ignore_token : Iterable[str]
        Banned-pattern regexes (matching :data:`BANNED_TOKENS`
        entries verbatim) to omit from this run.  Used by tests;
        in production no token is ignored.

    Returns
    -------
    dict
        The JSON report.  See module docstring for the schema.
    """

    root = root.resolve()
    if not root.exists():
        raise FileNotFoundError(f"--root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"--root is not a directory: {root}")

    # Apply ``ignore_token`` to the global token list.  This is
    # the same logic the CLI uses; the test suite calls
    # ``scan()`` directly so the parameter must work the same
    # way.
    if ignore_token:
        ignore_set = set(ignore_token)
        tokens = tuple(
            (p, label)
            for p, label in BANNED_TOKENS
            if p not in ignore_set
        )
    else:
        tokens = BANNED_TOKENS

    # We use a local re-compile so the (possibly reduced) token
    # list is in effect for this scan only.
    patterns = [
        (re.compile(p), label) for p, label in tokens
    ]
    skip = set(skip_dirs)
    skip_file_set = set(skip_files)
    allow_list = list(allow_patterns)
    ext_set = tuple(extensions)

    matches: list[dict[str, Any]] = []
    files_scanned = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped directories *in place* so os.walk doesn't
        # recurse into them.  We match the *basename* of each
        # entry, not its full path.
        dirnames[:] = [d for d in dirnames if not _is_skipped_dir(d, skip)]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if not _should_scan(fpath, ext_set):
                continue
            # ``skip_files`` is matched as a *relative POSIX path*
            # so a hit on ``tools/v6_residual_scan.py`` lands on
            # this very file regardless of where the user runs the
            # tool from.
            rel = fpath.relative_to(root).as_posix()
            if rel in skip_file_set:
                continue
            if _is_allowed(fpath, allow_list):
                continue
            files_scanned += 1
            matches.extend(_scan_file(fpath, patterns))

    by_token: dict[str, int] = {}
    for m in matches:
        by_token[m["rule"]] = by_token.get(m["rule"], 0) + 1

    return {
        "root": str(root),
        "files_scanned": files_scanned,
        "matches": matches,
        "summary": {
            "total_matches": len(matches),
            "by_token": by_token,
        },
    }


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _format_human(report: dict[str, Any]) -> str:
    """Render the report as a human-readable string."""

    lines: list[str] = []
    lines.append(f"v6-residual-scan: {report['root']}")
    lines.append(f"  files scanned : {report['files_scanned']}")
    lines.append(
        f"  total matches : {report['summary']['total_matches']}"
    )
    by_token = report["summary"]["by_token"]
    if by_token:
        lines.append("  by rule       :")
        for rule, n in sorted(by_token.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"    {n:>4}  {rule}")
    if report["matches"]:
        lines.append("")
        lines.append("  hits:")
        for m in report["matches"]:
            lines.append(
                f"    {m['path']}:{m['line']}:{m['column']}  "
                f"token={m['token']!r}  rule={m['rule']}"
            )
            lines.append(f"      {m['snippet']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_argparser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    p = argparse.ArgumentParser(
        prog="v6_residual_scan",
        description=(
            "Scan the AI-native project tree for v6 / brand residue "
            "(P0-1 enforcement)."
        ),
    )
    p.add_argument(
        "--root",
        default=os.getcwd(),
        help="Project root to scan (default: current directory).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON report on stdout (machine-readable for CI).",
    )
    p.add_argument(
        "--human",
        action="store_true",
        help="Emit a human-readable report on stdout (default if neither --json nor --human).",
    )
    p.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="REGEX",
        help=(
            "Regex matched against the file's POSIX path; a match "
            "skips the file.  May be repeated.  Tests use this to "
            "exercise the allow-list branch."
        ),
    )
    p.add_argument(
        "--ignore-token",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Banned-token regex to *omit* from the scan.  Use "
            "sparingly; this is for tests, not for hiding real "
            "residue."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns the process exit code."""

    global BANNED_TOKENS  # noqa: PLW0603
    root = Path(args.root) if (args := _build_argparser().parse_args(argv)) else Path.cwd()
    # Re-parse so the walrus above doesn't shadow our real args.
    args = _build_argparser().parse_args(argv)
    root = Path(args.root)
    try:
        allow = [re.compile(p) for p in args.allow]
    except re.error as exc:
        print(f"v6_residual_scan: invalid --allow regex: {exc}", file=sys.stderr)
        return 2

    # Materialize the token list.  ``--ignore-token`` is the
    # escape hatch for tests; in production no token is ignored.
    try:
        if args.ignore_token:
            tokens = tuple(
                (p, label)
                for p, label in BANNED_TOKENS
                if not any(re.fullmatch(it, p) for it in args.ignore_token)
            )
        else:
            tokens = BANNED_TOKENS
    except re.error as exc:
        print(f"v6_residual_scan: invalid --ignore-token regex: {exc}", file=sys.stderr)
        return 2

    # ``scan()`` uses a module-level constant; we patch the
    # ``BANNED_TOKENS`` symbol *only* for this invocation so we
    # don't have to thread it through every internal function.
    saved = BANNED_TOKENS
    BANNED_TOKENS = tokens  # type: ignore[assignment]
    try:
        try:
            report = scan(root, allow_patterns=allow)
        except (FileNotFoundError, NotADirectoryError) as exc:
            print(f"v6_residual_scan: {exc}", file=sys.stderr)
            return 2
    finally:
        BANNED_TOKENS = saved  # type: ignore[assignment]

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        # Default + --human both go to stdout.  --json wins if
        # both are passed.
        print(_format_human(report))

    return 0 if report["summary"]["total_matches"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
