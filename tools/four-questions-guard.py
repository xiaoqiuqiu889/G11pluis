#!/usr/bin/env python3
"""
four-questions-guard.py
=======================
CLI for the 4-Questions Self-Check (决策 6 of 《革命街没有尽头》).

This is the **P0** deliverable: every new scene / interaction is run
through this guard before commit.  Embedded in:
  * ``tools/content-studio/`` — runs on every "submit" click
  * ``tools/ci/.github/workflows/four-questions.yml`` — runs on every PR
    touching ``content/**/scenes/*``

Inputs
------
The CLI accepts one or more documents.  Each document is a YAML or
JSON file with one of two shapes:

  * scene_contract  — has ``required_anchors`` + ``allowed_beats`` etc.
                      The guard verifies the mandatory_echo list exists
                      (决策 3) and runs the additional checks.
  * interaction     — has at least one of the four-questions fields
                      (``artifact_updates``, ``event_log``,
                      ``belief_updates``, ``belief_matrix``,
                      ``turn_budget``, ``action_whitelist``,
                      ``causal_seeds``, ``far_echo_routes``).
                      The guard verifies Q1-Q4 are all touched.

Outputs
-------
A JSON report (one entry per input) on stdout, plus a human-readable
summary on stderr.  Exit code is 0 if every document passes, 1 if any
is blocking.

Usage
-----
    # Single document
    python tools/four-questions-guard.py content/.../scenes/photo_lab_2008.yaml

    # Many documents
    python tools/four-questions-guard.py content/.../scenes/*.yaml

    # JSON-only (machine-readable for CI)
    python tools/four-questions-guard.py --json content/.../scenes/*.yaml

    # Human-only
    python tools/four-questions-guard.py --human content/.../scenes/*.yaml

    # Restrict the check set (used by tests)
    python tools/four-questions-guard.py --checks Q1,Q2 --quiet doc.yaml

The tool is intentionally pure-stdlib (+ PyYAML) so the CI environment
needs nothing beyond ``pip install pyyaml``.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from typing import Sequence

# Force UTF-8 on stdout / stderr so the Chinese + emoji output does
# not crash on Windows code pages (e.g. GBK) or any other non-UTF-8
# locale.  CI environments and most modern terminals handle UTF-8
# natively; this only changes the encoding of the Python file
# objects, not the OS-level encoding of an attached terminal.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (ValueError, OSError):  # pragma: no cover - already-redirected streams
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
else:  # pragma: no cover - Python < 3.7
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (ValueError, OSError):  # pragma: no cover
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
else:  # pragma: no cover
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# When this CLI is invoked from a checkout, the sibling ``four_questions_guard_lib.py``
# lives next to it.  We add ``tools/`` to sys.path so the import is robust
# regardless of where the user invokes the tool from.
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import four_questions_guard_lib as lib  # noqa: E402


def _format_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="four-questions-guard",
        description=(
            "4-Questions Self-Check (决策 6) for 《革命街没有尽头》. "
            "Verifies that a scene contract or an interaction document "
            "satisfies the four core questions (Q1-Q4), the three additional "
            "checks (A-C), and the mandatory-echo binding (D-E)."
        ),
    )
    p.add_argument(
        "documents",
        nargs="+",
        help="One or more YAML / JSON files to validate.",
    )
    p.add_argument(
        "--checks",
        default=",".join(lib.ALL_CHECK_IDS),
        help=(
            "Comma-separated list of check IDs to evaluate. "
            f"Default: {','.join(lib.ALL_CHECK_IDS)}"
        ),
    )
    output = p.add_mutually_exclusive_group()
    output.add_argument(
        "--json",
        action="store_true",
        help="Print only the JSON report on stdout (suppress human summary).",
    )
    output.add_argument(
        "--human",
        action="store_true",
        help="Print only the human-readable summary (suppress JSON).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human summary on stderr.  Exit code is still set.",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Treat 'skipped' checks as failures.  Default is to count them "
            "as passed (skipped = 'not applicable to this document kind')."
        ),
    )
    p.add_argument(
        "--version",
        action="version",
        version="four-questions-guard 1.0.0",
    )
    return p


def _parse_check_ids(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    bad = [p for p in parts if p not in lib.ALL_CHECK_IDS]
    if bad:
        raise SystemExit(
            f"unknown check id(s): {bad}\n"
            f"available: {','.join(lib.ALL_CHECK_IDS)}"
        )
    return parts


def _emit_json(reports: Sequence[lib.GuardReport]) -> None:
    payload = {
        "version": "1.0.0",
        "documents": [r.to_dict() for r in reports],
        "summary": {
            "total_documents": len(reports),
            "passing_documents": sum(1 for r in reports if not r.blocking),
            "blocking_documents": sum(1 for r in reports if r.blocking),
        },
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _emit_human(reports: Sequence[lib.GuardReport]) -> None:
    for i, r in enumerate(reports):
        if i > 0:
            sys.stderr.write("\n")
        sys.stderr.write(r.to_human_readable() + "\n")
    blocked = [r for r in reports if r.blocking]
    if blocked:
        sys.stderr.write(
            f"\n❌ {len(blocked)}/{len(reports)} document(s) blocking the PR.\n"
        )
    else:
        sys.stderr.write(
            f"\n✅ all {len(reports)} document(s) pass the 4-questions guard.\n"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = _format_argparser().parse_args(argv)
    check_ids = _parse_check_ids(args.checks)

    reports: list[lib.GuardReport] = []
    any_error = False
    for path in args.documents:
        try:
            doc = lib.load_document(path)
        except (OSError, ValueError) as exc:
            sys.stderr.write(f"❌ failed to load {path}: {exc}\n")
            any_error = True
            continue
        report = lib.run_guard(doc, document_path=path, check_ids=check_ids)
        if args.strict:
            # Re-classify skipped as failures.
            new_results = []
            for r in report.results:
                if r.detail.startswith("skipped"):
                    new_results.append(lib.CheckResult(
                        id=r.id,
                        label=r.label,
                        passed=False,
                        evidence=r.evidence,
                        detail="(strict) " + r.detail,
                    ))
                else:
                    new_results.append(r)
            blocked_ids = set(lib.ALL_CHECK_IDS)
            reasons = [
                f"{r.id}: {r.detail}"
                for r in new_results
                if not r.passed and r.id in blocked_ids
            ]
            passed = sum(1 for r in new_results if r.passed)
            failed = sum(1 for r in new_results if not r.passed)
            summary = {"passed": passed, "failed": failed, "skipped": 0, "total": len(new_results)}
            report = lib.GuardReport(
                document_kind=report.document_kind,
                document_path=report.document_path,
                blocking=bool(reasons),
                blocking_reasons=reasons,
                results=new_results,
                summary=summary,
            )
        reports.append(report)

    # Output routing.
    if not args.quiet and not args.json:
        _emit_human(reports)
    if not args.human:
        _emit_json(reports)

    if any_error:
        return 2  # I/O error — separate from a clean BLOCK
    return 1 if any(r.blocking for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
