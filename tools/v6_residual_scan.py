#!/usr/bin/env python3
"""
v6_residual_scan.py
===================
Scans the project for residual v6-era brand / mechanism markers.

This is the **P0-1** and **P0-8** companion tool.  When the v6
client was rebranded and rebuilt as the AI-native "Game1Native"
remake, a list of v6-only identifiers had to disappear from the
active project.  This tool enforces that by scanning every
``*.yaml``, ``*.yml``, ``*.ts``, ``*.tsx``, ``*.py`` file under
the project root and flagging any line that contains a known
blacklist token.

Blacklist (case-sensitive)
--------------------------
Brand and product markers from the v6 era:

* ``JD-DEMO-*``   — the 5 v6 demo codes (replaced by
                     ``G1N-DEMO-{YEAR}-{NN}``)
* ``JD-``         — the broader JD / Jingdong prefix
* ``jingdong``    — lowercase / mixed-case English
* ``京东``         — the Chinese brand string

Forbidden mechanisms (v6-only data shapes):

* ``axisValues``       — v6 personality axis
* ``Scores``           — v6 scoring table
* ``simulatedPurchases`` — v6 fake-purchase ledger

The active project (``content/``, ``server/``, ``client/src/``,
``tools/``, ``db/``) is the scan target.  The historical
``_legacy_v6/`` directory is **excluded** because it is read-only
reference material and contains the original v6 sources by
design.

Outputs
-------
* JSON report to ``--report`` (default: stdout)
* Exit code:
  - ``0``  — zero hits
  - ``1``  — at least one hit
  - ``2``  — I/O / configuration error (e.g. unreadable dir)

The tool is intentionally pure-stdlib (no PyYAML) so the CI
environment only needs Python 3.x with no extras.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from typing import Iterable

# Force UTF-8 on stdout / stderr so the Chinese blacklist
# markers do not crash on Windows code pages (e.g. GBK) or any
# other non-UTF-8 locale.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (ValueError, OSError):  # pragma: no cover
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (ValueError, OSError):  # pragma: no cover
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
else:  # pragma: no cover
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


# Blacklist is a list of (token, kind) pairs.  We use substring
# match for the Chinese / English brands and the mechanism
# markers, and a regex match for the JD-DEMO-* codes so we can
# cover the whole prefix family (JD-DEMO-LOVE-01, JD-DEMO-ROAD-03,
# ...) with one pattern.
BLACKLIST: list[tuple[str, str, bool]] = [
    # (token, kind, is_regex)
    ("JD-DEMO-", "v6_demo_code_prefix", True),
    ("JD-", "jd_prefix", False),  # catches JD- in non-DEMO contexts
    ("jingdong", "jd_english", False),
    ("京东", "jd_chinese", False),
    ("axisValues", "v6_axis_values", False),
    ("Scores", "v6_scores_table", False),
    ("simulatedPurchases", "v6_simulated_purchases", False),
]

# Compile a single regex per pattern for fast line scanning.
# The compiled patterns are anchored on plain substring (no
# anchor) for substring matches, and on a leading "^.*" /
# trailing ".*$" for the regex pattern.  We use ``search`` for
# both so a token anywhere on the line is enough.
_COMPILED: list[tuple[re.Pattern[str], str, bool]] = []


def _compile_blacklist() -> None:
    for token, kind, is_regex in BLACKLIST:
        if is_regex:
            pattern = re.compile(token)
        else:
            pattern = re.compile(re.escape(token))
        _COMPILED.append((pattern, token, kind))


# Directories that are part of the *active* project.  Anything
# outside this allow-list is excluded.  In particular,
# ``_legacy_v6/`` is excluded because it is read-only reference
# material that *legitimately* contains the v6 markers.
DEFAULT_INCLUDE_DIRS: list[str] = [
    "analysis",
    "assets",
    "client",
    "content",
    "db",
    "docs",
    "server",
    "tests",
    "tools",
]

# Always excluded.  ``_legacy_v6`` is the v6 client and is
# supposed to keep the v6 markers (it is the historical source
# we are replacing).  ``node_modules``, ``__pycache__``,
# ``.pytest_cache`` etc. are dependency / cache directories that
# don't belong in source control and don't carry project intent.
DEFAULT_EXCLUDE_DIRS: list[str] = [
    "_legacy_v6",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".git",
    "dist",
    "build",
    "out",
    "coverage",
    ".next",
    "target",
]

DEFAULT_FILE_GLOBS: tuple[str, ...] = (
    "*.yaml",
    "*.yml",
    "*.ts",
    "*.tsx",
    "*.py",
)


def _is_excluded(path: str, exclude_dirs: Iterable[str]) -> bool:
    """Return True iff any segment of ``path`` is in ``exclude_dirs``."""

    norm = path.replace("\\", "/")
    parts = norm.split("/")
    for ex in exclude_dirs:
        if ex in parts:
            return True
    return False


def _iter_candidate_files(
    project_root: str,
    include_dirs: list[str],
    exclude_dirs: list[str],
    file_globs: tuple[str, ...],
) -> Iterable[str]:
    """Yield every file under ``project_root`` matching the include/exclude rules.

    Walks each top-level entry in ``include_dirs`` directly.  This
    is intentionally simple: the project is a fixed layout
    (``analysis/``, ``client/``, ``content/``, ``server/``,
    ``tools/``, ``tests/``, ``docs/``, ``db/``, ``assets/``)
    and we do not want to recursively descend into
    ``_legacy_v6/``, ``node_modules/`` or any other excluded
    top-level entry.
    """

    for inc in include_dirs:
        root = os.path.join(project_root, inc)
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune excluded directories in-place so ``os.walk``
            # does not descend into them.
            pruned: list[str] = []
            for d in dirnames:
                if d in exclude_dirs:
                    continue
                pruned.append(d)
            dirnames[:] = pruned
            for fn in filenames:
                if not any(fn.endswith(g[1:]) for g in file_globs):
                    continue
                # ``fn`` already ends with one of the globs
                yield os.path.join(dirpath, fn)


def _scan_file(path: str) -> list[dict[str, object]]:
    """Return a list of hit dicts for ``path``.

    Each hit has ``kind``, ``token``, ``line_number`` and
    ``line_text``.  An empty list means "no hits".
    """

    hits: list[dict[str, object]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, start=1):
                # Strip the trailing newline so the line text
                # does not include the EOL.
                text = line.rstrip("\n\r")
                for pattern, token, kind in _COMPILED:
                    if pattern.search(text):
                        hits.append(
                            {
                                "path": path,
                                "line_number": n,
                                "kind": kind,
                                "token": token,
                                "line_text": text[:400],
                            }
                        )
    except OSError as exc:
        return [
            {
                "path": path,
                "line_number": 0,
                "kind": "io_error",
                "token": "",
                "line_text": str(exc),
            }
        ]
    return hits


def _format_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="v6_residual_scan",
        description=(
            "Scan the active project for v6-era brand / mechanism "
            "markers.  The _legacy_v6/ directory is excluded by "
            "design.  Exit 0 = clean, 1 = at least one hit, "
            "2 = I/O error."
        ),
    )
    p.add_argument(
        "--root",
        default=os.getcwd(),
        help="Project root to scan.  Default: current directory.",
    )
    p.add_argument(
        "--include-dir",
        action="append",
        default=None,
        help=(
            "Top-level directory to scan.  May be repeated.  "
            f"Default: {','.join(DEFAULT_INCLUDE_DIRS)}"
        ),
    )
    p.add_argument(
        "--exclude-dir",
        action="append",
        default=None,
        help=(
            "Top-level directory to exclude.  May be repeated.  "
            f"Default: {','.join(DEFAULT_EXCLUDE_DIRS)}"
        ),
    )
    p.add_argument(
        "--report",
        default=None,
        help=(
            "Path to write the JSON report.  Default: stdout.  "
            "The directory must already exist."
        ),
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Treat I/O errors as scan failures (exit 1).  Default "
            "is to report them and exit 0."
        ),
    )
    p.add_argument(
        "--version",
        action="version",
        version="v6_residual_scan 1.0.0",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _format_argparser().parse_args(argv)
    _compile_blacklist()

    include_dirs = args.include_dir or list(DEFAULT_INCLUDE_DIRS)
    exclude_dirs = args.exclude_dir or list(DEFAULT_EXCLUDE_DIRS)
    project_root = os.path.abspath(args.root)

    hits: list[dict[str, object]] = []
    files_scanned = 0
    io_errors: list[dict[str, object]] = []
    for path in _iter_candidate_files(
        project_root, include_dirs, exclude_dirs, DEFAULT_FILE_GLOBS
    ):
        # Defense in depth: even though we restrict the walk to
        # the include dirs, an explicit path check stops a
        # future config mistake from leaking.
        if _is_excluded(path, exclude_dirs):
            continue
        files_scanned += 1
        for hit in _scan_file(path):
            if hit.get("kind") == "io_error":
                io_errors.append(hit)
            else:
                hits.append(hit)

    report = {
        "version": "1.0.0",
        "scanned_root": project_root,
        "include_dirs": include_dirs,
        "exclude_dirs": exclude_dirs,
        "file_globs": list(DEFAULT_FILE_GLOBS),
        "files_scanned": files_scanned,
        "blacklist": [
            {"token": tok, "kind": kind, "is_regex": is_regex}
            for tok, kind, is_regex in BLACKLIST
        ],
        "hit_count": len(hits),
        "io_error_count": len(io_errors),
        "hits": hits,
        "io_errors": io_errors,
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.write("\n")
    else:
        sys.stdout.write(payload)
        sys.stdout.write("\n")

    # Also print a human-readable summary on stderr.
    if hits:
        sys.stderr.write(
            f"❌ v6_residual_scan: {len(hits)} residual v6 marker(s) "
            f"in {files_scanned} file(s)\n"
        )
        for h in hits[:20]:
            sys.stderr.write(
                f"  {h['path']}:{h['line_number']}  "
                f"[{h['kind']}]  {h['line_text']!r}\n"
            )
        if len(hits) > 20:
            sys.stderr.write(f"  ... and {len(hits) - 20} more\n")
    else:
        sys.stderr.write(
            f"✅ v6_residual_scan: 0 hits in {files_scanned} file(s)\n"
        )

    if io_errors and args.strict:
        return 1
    if hits:
        return 1
    if io_errors:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
