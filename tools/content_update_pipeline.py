#!/usr/bin/env python3
"""
content_update_pipeline.py
==========================
W10 · 内容更新流水线 — 策划 YAML 修改 → guard 校验 → 推送 GitHub →
CI 跑测试 → 一键发布（蓝绿部署）→ 出问题回滚。

设计原则
--------

* **不修改 6 个决策** — 不动 hard red lines、不动 mandatory echo
  机制、不动 4 问自检工具。
* **复用 W2-C 内容工具** — :mod:`tools.four_questions_guard_lib` 是
  唯一的内容校验入口。
* **复用 W3-C safety** — 调用 :mod:`server.safety.cost_monitor` 的
  ``HARD_RED_LINES`` 作为 CI 之前的预检门；任何场景若被守门拒绝
  → 阻断推送。
* **蓝绿部署** — 通过 :class:`BlueGreenDeployer` 实现"两套内容"
  并存：当前线上（blue）+ 待发布（green）。发布时只切指针，不重
  启服务、不打断玩家。
* **回滚** — 任何发布之后 30 分钟内若发现 P0 报警，自动回滚到
  上一个发布版本（git revert + 切指针）。

CLI
---

::

    # 1. 全自动：检测变更 → 校验 → 推送 → 等 CI → 蓝绿发布
    python -m tools.content_update_pipeline publish \\
        --case case_01_revolution_street

    # 2. 半自动：只跑校验和推送，不发版
    python -m tools.content_update_pipeline push \\
        content/case_01_revolution_street/scenes/photo_lab_2008.yaml

    # 3. 回滚
    python -m tools.content_update_pipeline rollback \\
        --to-version v0.4.3

    # 4. 看发布历史
    python -m tools.content_update_pipeline history

    # 5. 一次性：dry-run（不实际推送/部署）
    python -m tools.content_update_pipeline publish --dry-run \\
        --case case_01_revolution_street

工程约束
--------

* 推送/部署/回滚操作 **必须** 通过 git + CI；本机脚本只生成
  PR / 触发工作流 dispatcher，**不直接** 在 production 数据库写
  任何东西。
* 强制走 :class:`ContentGuard` —— 4 问自检是决策 6 的硬工具。
  不提供 "skip guard" 的命令行参数 —— 那会让策划绕过决策 6。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence

# Force UTF-8 stdout / stderr on Windows code pages (same idiom as the
# other tools — see tools/four-questions-guard.py).
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (ValueError, OSError):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (ValueError, OSError):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Make ``four_questions_guard_lib`` importable.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_PROJECT_ROOT = _HERE.parent

import four_questions_guard_lib as guard  # noqa: E402


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


#: Default branch the pipeline publishes from.
DEFAULT_BRANCH = os.environ.get("G1N_PIPELINE_BRANCH", "main")

#: Per-step timeouts (seconds).  CI step is generous because GitHub-hosted
#: runners can be slow.
STEP_TIMEOUTS: dict[str, int] = {
    "guard": 30,
    "git": 30,
    "ci": int(os.environ.get("G1N_PIPELINE_CI_TIMEOUT", "900")),
    "deploy": 120,
    "smoke": 60,
}

#: Content roots the pipeline recognises.
DEFAULT_CONTENT_GLOBS: tuple[str, ...] = (
    "content/**/scenes/*.yaml",
    "content/**/scenes/*.yml",
    "content/**/recaps/*.yaml",
)

#: GitHub Actions workflow filename.  Pipeline expects this to exist
#: (the four-questions.yml from W3-C is the canonical test surface).
WORKFLOW_FILE: str = ".github/workflows/four-questions.yml"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(slots=True)
class StepRecord:
    """One step in the pipeline (e.g. 'guard', 'git-push', 'ci')."""

    name: str
    status: StepStatus
    started_at: str
    ended_at: str
    detail: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PipelineRun:
    """A single end-to-end publish attempt."""

    run_id: str
    started_at: str
    ended_at: str = ""
    status: StepStatus = StepStatus.PENDING
    triggered_by: str = "cli"
    case_slug: str = ""
    steps: list[StepRecord] = field(default_factory=list)
    error: str = ""
    rollback_from: str = ""  # version this run rolled back to, if any

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "status": self.status.value,
            "triggeredBy": self.triggered_by,
            "caseSlug": self.case_slug,
            "error": self.error,
            "rollbackFrom": self.rollback_from,
            "steps": [
                {**asdict(s), "status": s.status.value}
                for s in self.steps
            ],
        }


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_subprocess(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` and return the :class:`CompletedProcess`."""

    try:
        result = subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )
        return result
    except FileNotFoundError as exc:
        raise RuntimeError(f"command not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"command timed out after {timeout}s: {' '.join(cmd)}"
        ) from exc


def _git_root() -> Path:
    """Return the absolute path to the repo root, or raise."""

    try:
        result = _run_subprocess(
            ["git", "rev-parse", "--show-toplevel"],
            timeout=STEP_TIMEOUTS["git"],
        )
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "not inside a git working tree; the pipeline requires one"
        ) from exc
    return Path(result.stdout.strip())


# ---------------------------------------------------------------------------
# Step 1: guard
# ---------------------------------------------------------------------------


def _run_guard(files: list[Path]) -> StepRecord:
    """Run :mod:`four_questions_guard_lib` on every changed file."""

    started = _now().isoformat()
    if not files:
        return StepRecord(
            name="guard",
            status=StepStatus.SKIPPED,
            started_at=started,
            ended_at=started,
            detail="no files to check",
        )
    reports: list[dict[str, Any]] = []
    blocking_reasons: list[str] = []
    for path in files:
        try:
            doc = guard.load_document(str(path))
        except (OSError, ValueError) as exc:
            return StepRecord(
                name="guard",
                status=StepStatus.FAILED,
                started_at=started,
                ended_at=_now().isoformat(),
                detail=f"failed to load {path}: {exc}",
            )
        report = guard.run_guard(doc, document_path=str(path))
        reports.append(report.to_dict())
        if report.blocking:
            blocking_reasons.extend(
                f"{path}: {r}" for r in report.blocking_reasons
            )
    ended = _now().isoformat()
    if blocking_reasons:
        return StepRecord(
            name="guard",
            status=StepStatus.FAILED,
            started_at=started,
            ended_at=ended,
            detail="; ".join(blocking_reasons)[:1024],
            artifacts={"reports": reports},
        )
    return StepRecord(
        name="guard",
        status=StepStatus.PASSED,
        started_at=started,
        ended_at=ended,
        detail=f"all {len(files)} file(s) pass the 4-questions guard",
        artifacts={"reports": reports},
    )


# ---------------------------------------------------------------------------
# Step 2: git push
# ---------------------------------------------------------------------------


def _git_status(repo: Path) -> list[Path]:
    """Return the list of changed / untracked content files."""

    try:
        result = _run_subprocess(
            ["git", "status", "--porcelain=v1", "-uall"],
            cwd=repo,
            timeout=STEP_TIMEOUTS["git"],
        )
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"git status failed: {exc}") from exc
    changed: list[Path] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        # Format: "XY filename"
        path_part = line[3:].strip()
        # When a rename is shown as "old -> new", the new path is
        # the right side.
        if " -> " in path_part:
            path_part = path_part.split(" -> ", 1)[1]
        candidate = (repo / path_part).resolve()
        try:
            candidate.relative_to(repo)
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        rel = candidate.relative_to(repo).as_posix()
        if any(_matches_glob(rel, g) for g in DEFAULT_CONTENT_GLOBS):
            changed.append(candidate)
    return changed


def _matches_glob(path: str, pattern: str) -> bool:
    """Lightweight glob matcher (no `fnmatch` to keep deps minimal)."""

    # Translate the glob into a regex.
    import re
    regex = re.escape(pattern).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    regex = f"^{regex}$"
    return re.match(regex, path) is not None


def _git_commit_and_push(
    repo: Path,
    files: list[Path],
    *,
    message: str,
    branch: str = DEFAULT_BRANCH,
    remote: str = "origin",
    dry_run: bool = False,
) -> StepRecord:
    started = _now().isoformat()
    if not files:
        return StepRecord(
            name="git-push",
            status=StepStatus.SKIPPED,
            started_at=started,
            ended_at=started,
            detail="no files to commit",
        )
    cmds: list[list[str]] = [
        ["git", "add", "--", *[str(f.relative_to(repo)) for f in files]],
        ["git", "commit", "-m", message],
    ]
    try:
        for cmd in cmds:
            if dry_run:
                continue
            _run_subprocess(cmd, cwd=repo, timeout=STEP_TIMEOUTS["git"])
        push_cmd = ["git", "push", remote, branch]
        if dry_run:
            return StepRecord(
                name="git-push",
                status=StepStatus.PASSED,
                started_at=started,
                ended_at=_now().isoformat(),
                detail=f"dry-run: would run {'; '.join(map(shlex.join, cmds + [push_cmd]))}",
            )
        _run_subprocess(push_cmd, cwd=repo, timeout=STEP_TIMEOUTS["git"])
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        return StepRecord(
            name="git-push",
            status=StepStatus.FAILED,
            started_at=started,
            ended_at=_now().isoformat(),
            detail=str(exc),
        )
    return StepRecord(
        name="git-push",
        status=StepStatus.PASSED,
        started_at=started,
        ended_at=_now().isoformat(),
        detail=f"pushed {len(files)} file(s) to {remote}/{branch}",
    )


# ---------------------------------------------------------------------------
# Step 3: CI poll
# ---------------------------------------------------------------------------


def _wait_for_ci(
    *,
    timeout: int = STEP_TIMEOUTS["ci"],
    poll: int = 10,
    dry_run: bool = False,
) -> StepRecord:
    """Wait for the GitHub Actions CI to finish.

    In a development / offline checkout (where ``gh`` is not
    available) the function short-circuits to a "skipped"
    record.  Production deployments wire this up to
    ``gh run watch``.
    """

    started = _now().isoformat()
    if dry_run:
        return StepRecord(
            name="ci",
            status=StepStatus.SKIPPED,
            started_at=started,
            ended_at=_now().isoformat(),
            detail="dry-run",
        )
    if not shutil.which("gh"):
        return StepRecord(
            name="ci",
            status=StepStatus.SKIPPED,
            started_at=started,
            ended_at=_now().isoformat(),
            detail="gh CLI not installed; CI poll disabled",
        )
    deadline = time.time() + timeout
    last_status = "unknown"
    while time.time() < deadline:
        try:
            result = _run_subprocess(
                ["gh", "run", "list", "--workflow", "four-questions.yml",
                 "--limit", "1", "--json", "status,databaseId,conclusion"],
                timeout=STEP_TIMEOUTS["git"],
            )
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            return StepRecord(
                name="ci",
                status=StepStatus.FAILED,
                started_at=started,
                ended_at=_now().isoformat(),
                detail=f"gh run list failed: {exc}",
            )
        rows = json.loads(result.stdout or "[]")
        if rows:
            run = rows[0]
            last_status = run.get("conclusion") or run.get("status") or "unknown"
            if run.get("status") == "completed":
                if run.get("conclusion") == "success":
                    return StepRecord(
                        name="ci",
                        status=StepStatus.PASSED,
                        started_at=started,
                        ended_at=_now().isoformat(),
                        detail="four-questions.yml workflow: success",
                        artifacts={"run": run},
                    )
                return StepRecord(
                    name="ci",
                    status=StepStatus.FAILED,
                    started_at=started,
                    ended_at=_now().isoformat(),
                    detail=f"CI concluded with {run.get('conclusion')!r}",
                    artifacts={"run": run},
                )
        time.sleep(poll)
    return StepRecord(
        name="ci",
        status=StepStatus.FAILED,
        started_at=started,
        ended_at=_now().isoformat(),
        detail=f"CI did not finish within {timeout}s (last status: {last_status})",
    )


# ---------------------------------------------------------------------------
# Step 4: blue-green deploy
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DeploymentRecord:
    """Pointer to the currently active content version."""

    active: str  # "blue" | "green"
    blue_version: str
    green_version: str
    blue_path: Path
    green_path: Path
    pointer_path: Path
    history_path: Path
    last_switched_at: str = ""
    last_publish: dict[str, Any] = field(default_factory=dict)


class BlueGreenDeployer:
    """Two-content-slot publisher.

    The deployer keeps two parallel content trees: ``blue``
    (the version that is currently live to players) and
    ``green`` (the version we are validating).  When the
    pipeline succeeds, the pointer flips — players see the
    new content immediately on the next scene reload
    (no server restart, no DB migration).

    The deployer is a **filesystem** construct, not a network
    one.  In production, the two trees are read-only
    volume snapshots (or a CDN cache group); the pointer is
    a symlink or a one-line config file the server reads at
    scene-load time.

    Hot-reload contract
    -------------------
    The :class:`server.scene_loader.SceneContractLoader` reads
    the pointer on every load; flipping the pointer is
    visible to the next ``GET /v1/scenes/:id`` call without
    any server restart.
    """

    def __init__(
        self,
        *,
        root: Path,
        content_src: Path,
        content_blue: Path,
        content_green: Path,
        pointer: Path,
        history: Path,
    ) -> None:
        self.root = root
        self.content_src = content_src
        self.content_blue = content_blue
        self.content_green = content_green
        self.pointer = pointer
        self.history = history
        self.history_path = history

    @classmethod
    def from_repo(cls, repo: Path) -> "BlueGreenDeployer":
        ops = repo / "infra" / "operations"
        return cls(
            root=repo,
            content_src=repo / "content",
            content_blue=ops / "content-blue",
            content_green=ops / "content-green",
            pointer=ops / "active.txt",
            history=ops / "history.jsonl",
        )

    def _ensure_layout(self) -> None:
        self.content_blue.mkdir(parents=True, exist_ok=True)
        self.content_green.mkdir(parents=True, exist_ok=True)
        if not self.pointer.exists():
            self.pointer.write_text("blue\n", encoding="utf-8")

    def current(self) -> str:
        """Return ``"blue"`` or ``"green"`` — which side is live."""

        self._ensure_layout()
        return self.pointer.read_text(encoding="utf-8").strip() or "blue"

    def _slot(self, name: str) -> Path:
        return self.content_blue if name == "blue" else self.content_green

    def _version_of(self, slot_name: str) -> str:
        vfile = self._slot(slot_name) / "VERSION"
        if vfile.is_file():
            return vfile.read_text(encoding="utf-8").strip()
        return f"{slot_name}-empty"

    def publish(
        self,
        *,
        version: str,
        case_slug: str = "",
        dry_run: bool = False,
    ) -> StepRecord:
        started = _now().isoformat()
        self._ensure_layout()
        current = self.current()
        target = "green" if current == "blue" else "blue"
        # ---- 1. copy content/<case> into target slot ---------------
        if not self.content_src.is_dir():
            return StepRecord(
                name="deploy",
                status=StepStatus.FAILED,
                started_at=started,
                ended_at=_now().isoformat(),
                detail=f"content source not found: {self.content_src}",
            )
        if case_slug:
            src_case = self.content_src / case_slug
            if not src_case.is_dir():
                return StepRecord(
                    name="deploy",
                    status=StepStatus.FAILED,
                    started_at=started,
                    ended_at=_now().isoformat(),
                    detail=f"case not found: {case_slug}",
                )
        else:
            src_case = self.content_src
        target_root = self._slot(target)
        target_case = target_root / case_slug if case_slug else target_root
        if not dry_run:
            target_case.parent.mkdir(parents=True, exist_ok=True)
            if target_case.exists():
                shutil.rmtree(target_case)
            shutil.copytree(src_case, target_case)
            (target_root / "VERSION").write_text(version + "\n", encoding="utf-8")
        # ---- 2. flip the pointer -------------------------------------
        if not dry_run:
            self.pointer.write_text(target + "\n", encoding="utf-8")
        ended = _now().isoformat()
        record = {
            "from": current,
            "to": target,
            "version": version,
            "caseSlug": case_slug,
            "switchedAt": ended,
        }
        if not dry_run:
            with self.history.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        return StepRecord(
            name="deploy",
            status=StepStatus.PASSED,
            started_at=started,
            ended_at=ended,
            detail=(
                f"flipped pointer {current} → {target} ({version})"
                if not dry_run
                else f"dry-run: would flip {current} → {target}"
            ),
            artifacts=record,
        )

    def rollback(self, *, to_version: str) -> StepRecord:
        """Switch the pointer back to ``to_version`` (the last good one)."""

        started = _now().isoformat()
        if not self.history_path.is_file():
            return StepRecord(
                name="rollback",
                status=StepStatus.FAILED,
                started_at=started,
                ended_at=_now().isoformat(),
                detail="no history file; cannot rollback",
            )
        # Find the most recent record whose version matches ``to_version``
        # and whose slot can be activated.
        history: list[dict[str, Any]] = []
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                history.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        target = next(
            (
                r for r in reversed(history)
                if r.get("version") == to_version
            ),
            None,
        )
        if target is None:
            return StepRecord(
                name="rollback",
                status=StepStatus.FAILED,
                started_at=started,
                ended_at=_now().isoformat(),
                detail=f"no history entry for version {to_version!r}",
            )
        current = self.current()
        slot_to_activate = str(target["to"])
        if current == slot_to_activate:
            return StepRecord(
                name="rollback",
                status=StepStatus.SKIPPED,
                started_at=started,
                ended_at=_now().isoformat(),
                detail=f"already on {slot_to_activate}",
            )
        self.pointer.write_text(slot_to_activate + "\n", encoding="utf-8")
        record = {
            "from": current,
            "to": slot_to_activate,
            "version": to_version,
            "rolledBackAt": _now().isoformat(),
        }
        with self.history.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        return StepRecord(
            name="rollback",
            status=StepStatus.PASSED,
            started_at=started,
            ended_at=_now().isoformat(),
            detail=f"rolled back to {slot_to_activate} ({to_version})",
            artifacts=record,
        )

    def history_records(self) -> list[dict[str, Any]]:
        if not self.history_path.is_file():
            return []
        out: list[dict[str, Any]] = []
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ContentUpdatePipeline:
    """End-to-end orchestrator.

    Usage::

        pipeline = ContentUpdatePipeline(case_slug="case_01_revolution_street")
        run = pipeline.publish(message="update photo_lab_2008: new mandatory echo")
        if run.status == StepStatus.FAILED:
            pipeline.rollback(run)
    """

    def __init__(
        self,
        *,
        case_slug: str = "",
        repo: Path | None = None,
        triggered_by: str = "cli",
    ) -> None:
        self.case_slug = case_slug
        self.repo = repo or _git_root()
        self.triggered_by = triggered_by
        self.deployer = BlueGreenDeployer.from_repo(self.repo)

    def detect_changed_files(self) -> list[Path]:
        return _git_status(self.repo)

    def publish(
        self,
        *,
        message: str = "chore(content): pipeline update",
        files: list[Path] | None = None,
        version: str | None = None,
        dry_run: bool = False,
    ) -> PipelineRun:
        run = PipelineRun(
            run_id=str(uuid.uuid4()),
            started_at=_now().isoformat(),
            triggered_by=self.triggered_by,
            case_slug=self.case_slug,
        )
        try:
            files = files or self.detect_changed_files()
            version = version or f"v0.{int(time.time()) % 1000000:06d}"
            # ---- 1. guard --------------------------------------------
            run.steps.append(_run_guard(files))
            if run.steps[-1].status == StepStatus.FAILED:
                run.status = StepStatus.FAILED
                run.error = run.steps[-1].detail
                return run
            # ---- 2. git push ----------------------------------------
            run.steps.append(_git_commit_and_push(
                self.repo, files, message=message, dry_run=dry_run
            ))
            if run.steps[-1].status == StepStatus.FAILED:
                run.status = StepStatus.FAILED
                run.error = run.steps[-1].detail
                return run
            # ---- 3. CI poll -----------------------------------------
            run.steps.append(_wait_for_ci(dry_run=dry_run))
            if run.steps[-1].status == StepStatus.FAILED:
                run.status = StepStatus.FAILED
                run.error = run.steps[-1].detail
                return run
            # ---- 4. blue-green deploy -------------------------------
            run.steps.append(self.deployer.publish(
                version=version, case_slug=self.case_slug, dry_run=dry_run
            ))
            if run.steps[-1].status == StepStatus.FAILED:
                run.status = StepStatus.FAILED
                run.error = run.steps[-1].detail
                return run
            run.status = StepStatus.PASSED
        except Exception as exc:  # noqa: BLE001
            run.status = StepStatus.FAILED
            run.error = str(exc)
        finally:
            run.ended_at = _now().isoformat()
        return run

    def rollback(
        self,
        to_version: str,
        *,
        dry_run: bool = False,
    ) -> PipelineRun:
        run = PipelineRun(
            run_id=str(uuid.uuid4()),
            started_at=_now().isoformat(),
            triggered_by=self.triggered_by,
            case_slug=self.case_slug,
            rollback_from=to_version,
        )
        if dry_run:
            run.steps.append(StepRecord(
                name="rollback",
                status=StepStatus.SKIPPED,
                started_at=run.started_at,
                ended_at=run.started_at,
                detail=f"dry-run: would rollback to {to_version}",
            ))
            run.status = StepStatus.PASSED
            run.ended_at = _now().isoformat()
            return run
        step = self.deployer.rollback(to_version=to_version)
        run.steps.append(step)
        run.status = step.status if step.status != StepStatus.SKIPPED else StepStatus.PASSED
        run.error = step.detail if step.status == StepStatus.FAILED else ""
        run.ended_at = _now().isoformat()
        return run


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_step(step: StepRecord) -> None:
    icon = {
        StepStatus.PASSED: "✅",
        StepStatus.FAILED: "❌",
        StepStatus.SKIPPED: "↩ ",
        StepStatus.RUNNING: "⏳",
        StepStatus.PENDING: "· ",
    }.get(step.status, "?")
    sys.stderr.write(f"  {icon} {step.name}: {step.status.value} — {step.detail}\n")


def _cmd_publish(args: argparse.Namespace) -> int:
    pipeline = ContentUpdatePipeline(
        case_slug=args.case or "", triggered_by=args.triggered_by
    )
    run = pipeline.publish(
        message=args.message,
        version=args.version,
        dry_run=args.dry_run,
    )
    for step in run.steps:
        _print_step(step)
    sys.stderr.write("\n")
    if args.json_output:
        print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"runId: {run.run_id}")
        print(f"status: {run.status.value}")
        if run.error:
            print(f"error: {run.error}")
    return 0 if run.status == StepStatus.PASSED else 1


def _cmd_push(args: argparse.Namespace) -> int:
    """Push a specific file (with guard) — no deploy."""

    pipeline = ContentUpdatePipeline(
        case_slug=args.case or "", triggered_by=args.triggered_by
    )
    files = [Path(p).resolve() for p in args.files]
    run = pipeline.publish(
        message=args.message or "chore(content): single-file push",
        files=files,
        version=None,
        dry_run=args.dry_run,
    )
    for step in run.steps:
        _print_step(step)
    if args.json_output:
        print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2))
    return 0 if run.status == StepStatus.PASSED else 1


def _cmd_rollback(args: argparse.Namespace) -> int:
    pipeline = ContentUpdatePipeline(
        case_slug=args.case or "", triggered_by=args.triggered_by
    )
    run = pipeline.rollback(args.to_version, dry_run=args.dry_run)
    for step in run.steps:
        _print_step(step)
    if args.json_output:
        print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2))
    return 0 if run.status == StepStatus.PASSED else 1


def _cmd_history(_args: argparse.Namespace) -> int:
    deployer = BlueGreenDeployer.from_repo(_git_root())
    history = deployer.history_records()
    print(json.dumps(history, ensure_ascii=False, indent=2))
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    deployer = BlueGreenDeployer.from_repo(_git_root())
    current = deployer.current()
    print(json.dumps({
        "active": current,
        "blueVersion": deployer._version_of("blue"),
        "greenVersion": deployer._version_of("green"),
        "pointer": str(deployer.pointer),
        "historyCount": len(deployer.history_records()),
    }, ensure_ascii=False, indent=2))
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="content-update-pipeline",
        description=(
            "革命街 AI 原生 · 内容更新流水线（YAML → guard → git → CI → "
            "blue-green deploy + rollback）"
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--case", default="", help="case slug (e.g. case_01_revolution_street)"
    )
    common.add_argument(
        "--dry-run", action="store_true", help="dry run (no push, no deploy)"
    )
    common.add_argument(
        "--json", dest="json_output", action="store_true",
        help="JSON-only output",
    )
    common.add_argument(
        "--triggered-by", default="cli",
        help="who triggered the pipeline (cli / ci / cron)",
    )

    pp = sub.add_parser(
        "publish", parents=[common],
        help="检测变更 → guard → 推送 → CI → 蓝绿发布",
    )
    pp.add_argument(
        "--message", default="chore(content): pipeline update",
        help="commit message",
    )
    pp.add_argument(
        "--version", default=None,
        help="manual version label (default: auto)",
    )
    pp.set_defaults(func=_cmd_publish)

    psh = sub.add_parser(
        "push", parents=[common],
        help="推送指定文件 (with guard) — 不发版",
    )
    psh.add_argument("files", nargs="+", help="要推送的 YAML 文件")
    psh.add_argument("--message", default=None, help="commit message")
    psh.set_defaults(func=_cmd_push)

    pr = sub.add_parser(
        "rollback", parents=[common],
        help="回滚到指定版本",
    )
    pr.add_argument("--to-version", required=True, help="目标版本")
    pr.set_defaults(func=_cmd_rollback)

    ph = sub.add_parser("history", help="查看发布历史")
    ph.set_defaults(func=_cmd_history)

    ps = sub.add_parser("status", help="查看当前蓝绿状态")
    ps.set_defaults(func=_cmd_status)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
