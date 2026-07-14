# CI Integration — four-questions-guard

This directory contains the CI configurations that make the
4-questions self-check (决策 6) **non-bypassable**.

## Files

| File | Platform | What it does |
|------|----------|--------------|
| `.github/workflows/four-questions.yml` | GitHub Actions | Triggers on `content/**/scenes/*` changes, runs the guard, blocks the PR. |
| `.gitlab-ci.yml` | GitLab CI | GitLab equivalent of the GitHub workflow. |

## What gets blocked

A pull request / merge request is **blocked** when:

1. The unit tests for the guard fail (means the tool itself has regressed).
2. Any scene under `content/**/scenes/*` fails the 4-questions guard
   (exit code 1).
3. The tool itself crashes (exit code 2 — I/O error).

A scene contract is considered to fail when **any** of the following
is true:

* **Q1-Q4 (decision 1)** — for an interaction document, all four
  questions must be touched.
* **D (decision 3)** — the scene must explicitly declare its
  `mandatory_echoes` list.  This is the AI-must-not-free-style
  constraint; if a scene lacks the list, every echo the AI generates
  is ungrounded.
* **A (decision 6)** — any `forbidden_reveals` violation.
* **B (decision 6)** — `current_turn > max_turns` would blow the
  budget.
* **C (decision 6)** — an artifact has multiple owners in the listing.

The full list of check IDs is in
`tools/four_questions_guard_lib.py` (look for `ALL_CHECK_IDS`).

## Running locally

```bash
# Single scene
python tools/four-questions-guard.py content/.../scenes/photo_lab_2008.yaml

# All scenes
python tools/four-questions-guard.py content/**/scenes/*.yaml

# Human-readable only
python tools/four-questions-guard.py --human content/**/scenes/*.yaml

# Machine-readable JSON
python tools/four-questions-guard.py --json content/**/scenes/*.yaml
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | All documents pass. |
| 1 | At least one document is blocking. |
| 2 | I/O error (e.g. file not found). |

## Adding a new scene

1. Create the scene YAML under `content/<case>/scenes/`.
2. Add a non-empty `mandatory_echoes` list.  **This is non-negotiable.**
3. Run `python tools/four-questions-guard.py <your-scene>.yaml` —
   the output must be ✅ PASS before commit.
4. Open a PR — CI will re-run the guard and block the PR if the tool
   disagrees.

## What "blocking" looks like in CI

A red ❌ on the `guard` job in the PR page.  The job log contains the
full human-readable report and a `::error::` annotation with a hint
to run the tool locally.
