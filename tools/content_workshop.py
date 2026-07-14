#!/usr/bin/env python3
"""
content_workshop.py
===================
W10 · 策划后台 — 让策划上传 YAML → 自动校验 → 4 项自检 → 显示
通过/阻断 + 阻断原因。

设计原则
--------

* **不修改 6 个决策** — 不绕过 mandatory echo 校验 (决策 3)，
  不绕过 4 项自检工具 (决策 6)。
* **不修改 scene_loader 的 cache 协议** — 只调用新增的
  :meth:`reload` 方法。
* **复用 W2-C tools/** — 全部校验走
  :mod:`tools.four_questions_guard_lib`，**不重新实现**。
* **支持 hot-reload** — 通过 :meth:`SceneContractLoader.reload`
  让新 YAML 立即生效，**不重启服务**。
* **显示 narrative contract 校验结果** — 决策 3 要求
  mandatory echo 必须在合同中显式登记。

CLI
---

::

    # 校验一个 YAML (不写盘)
    python -m tools.content_workshop validate \\
        content/case_01_revolution_street/scenes/photo_lab_2008.yaml

    # 上传一个 YAML：写盘 → 4 项自检 → 阻断时显示原因
    python -m tools.content_workshop upload \\
        content/case_01_revolution_street/scenes/photo_lab_2008.yaml

    # 上传 + 校验通过后 hot-reload (不重启服务)
    python -m tools.content_workshop upload \\
        content/case_01_revolution_street/scenes/photo_lab_2008.yaml \\
        --hot-reload

    # 查看 hot-reload 状态
    python -m tools.content_workshop status

    # 列出所有可校验的 YAML
    python -m tools.content_workshop list
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

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

# Path setup — make ``tools.four_questions_guard_lib`` and the engine
# packages importable.
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "server") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "server"))

import four_questions_guard_lib as guard  # noqa: E402

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

try:
    from scene_loader import (  # type: ignore  # noqa: E402
        SCENES_IN_ORDER,
        SceneContractLoader,
        get_default_loader,
    )
    _SCENE_LOADER_OK = True
except Exception:  # noqa: BLE001
    SceneContractLoader = None  # type: ignore
    get_default_loader = None  # type: ignore
    _SCENE_LOADER_OK = False


# ---------------------------------------------------------------------------
# Status types
# ---------------------------------------------------------------------------


class CheckVerdict(str, Enum):
    PASS = "pass"
    BLOCK = "block"
    SKIP = "skip"


@dataclass(slots=True)
class CheckResultRow:
    """One row of the workshop's check table.

    A row is *block* if it would block the upload;
    *pass* if it succeeds; *skip* if it does not apply
    to the document kind.
    """

    check_id: str
    label: str
    verdict: CheckVerdict
    detail: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkId": self.check_id,
            "label": self.label,
            "verdict": self.verdict.value,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


@dataclass(slots=True)
class WorkshopReport:
    """The result of a validate / upload / hot-reload call."""

    document_path: str
    document_kind: str
    overall: CheckVerdict
    checks: list[CheckResultRow] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    contract_summary: dict[str, Any] = field(default_factory=dict)
    written: bool = False
    hot_reloaded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "documentPath": self.document_path,
            "documentKind": self.document_kind,
            "overall": self.overall.value,
            "checks": [c.to_dict() for c in self.checks],
            "blockingReasons": list(self.blocking_reasons),
            "suggestions": list(self.suggestions),
            "contractSummary": dict(self.contract_summary),
            "written": self.written,
            "hotReloaded": self.hot_reloaded,
        }


# ---------------------------------------------------------------------------
# 4 项自检 — 决策 6 复刻
# ---------------------------------------------------------------------------


def _add_check(
    report: WorkshopReport,
    *,
    check_id: str,
    label: str,
    passed: bool,
    detail: str,
    evidence: Iterable[str] = (),
    block_on_fail: bool = True,
) -> None:
    verdict = CheckVerdict.PASS if passed else (
        CheckVerdict.BLOCK if block_on_fail else CheckVerdict.SKIP
    )
    report.checks.append(CheckResultRow(
        check_id=check_id, label=label, verdict=verdict, detail=detail,
        evidence=list(evidence),
    ))
    if verdict is CheckVerdict.BLOCK:
        report.blocking_reasons.append(f"[{check_id}] {label}: {detail}")


def _run_four_questions(report: WorkshopReport, doc: dict[str, Any]) -> None:
    """Run the canonical 4-questions guard and record each check.

    The W2-C :mod:`tools.four_questions_guard_lib` is the
    single source of truth — we translate its
    :class:`CheckResult` rows into workshop rows so the
    UI shows them in the same column order.  The
    :attr:`GuardReport.blocking` field is the canonical
    signal of "this would block the PR"; the per-row
    advisory / blocking policy is owned by the guard
    (e.g. Q1/Q2/Q4 are advisory on ``scene_contract``).
    """

    try:
        result = guard.run_guard(doc, document_path=report.document_path)
    except (OSError, ValueError) as exc:
        _add_check(
            report,
            check_id="guard.load",
            label="YAML 解析",
            passed=False,
            detail=f"无法加载文档: {exc}",
        )
        report.overall = CheckVerdict.BLOCK
        return
    # Map of check_id → "would block".  Use the same
    # per-check policy the guard uses internally.
    block_lookup: set[str] = set()
    for reason in result.blocking_reasons:
        # reasons look like "Q1_changes_world_state: no world-state change..."
        check_id = reason.split(":", 1)[0].strip()
        block_lookup.add(check_id)
    for r in result.results:
        block_on_fail = r.id in block_lookup
        _add_check(
            report,
            check_id=r.id,
            label=r.label,
            passed=r.passed,
            detail=r.detail,
            evidence=r.evidence,
            block_on_fail=block_on_fail,
        )
    if result.blocking:
        report.overall = CheckVerdict.BLOCK


# ---------------------------------------------------------------------------
# Narrative contract validation
# ---------------------------------------------------------------------------


def _extract_mandatory_echoes(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the scene's declared ``mandatory_echoes`` (decision 3)."""

    return list(doc.get("mandatory_echoes", []) or [])


def _extract_optional_echoes(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the scene's declared ``optional_echoes``."""

    return list(doc.get("optional_echoes", []) or [])


def _extract_npc_recall_echoes(doc: dict[str, Any]) -> set[str]:
    """Return the set of echo IDs the NPC may *proactively* raise.

    Per decision 3: the NPC's proactive echo must be in
    the mandatory list.  The contract declares the
    triggers that *can* lead to a proactive raise
    (e.g. ``trigger: player_did_X``); any echo whose
    ``ai_director_must_invoke`` is true is potentially
    raised.
    """

    mandatory = _extract_mandatory_echoes(doc)
    return {
        str(m.get("id"))
        for m in mandatory
        if m.get("ai_director_must_invoke")
    }


def _validate_narrative_contract(
    report: WorkshopReport, doc: dict[str, Any],
) -> dict[str, Any]:
    """Run the decision 3 + 1 contract validation.

    Returns a contract summary dict; also appends check
    rows.  The summary is the payload the UI shows in
    the "narrative contract" panel.
    """

    summary: dict[str, Any] = {
        "sceneId": doc.get("scene_id"),
        "era": doc.get("era"),
        "maxTurns": doc.get("max_turns"),
        "totalActionBudget": doc.get("total_action_budget"),
        "cast": doc.get("cast", []),
        "mandatoryEchoes": _extract_mandatory_echoes(doc),
        "optionalEchoes": _extract_optional_echoes(doc),
    }
    mandatory = _extract_mandatory_echoes(doc)
    # Decision 3 — mandatory echoes must be non-empty
    # for scenes after 2008 (reunion_2024 should have 5,
    # farewell_2011 should have ≥ 2 with one of them
    # referencing 2008).  The check is a heuristic; the
    # exact rule is the brief, and it varies by scene.
    scene_id = doc.get("scene_id", "")
    expected_minimums = {
        "photo_lab_2008": 2,
        "farewell_2011": 2,
        "reunion_2024": 5,
    }
    minimum = expected_minimums.get(scene_id, 1)
    _add_check(
        report,
        check_id="contract.mandatory_echo_count",
        label="Mandatory Echo 数量",
        passed=len(mandatory) >= minimum,
        detail=(
            f"{scene_id}: 实际 {len(mandatory)} 个 mandatory echo, "
            f"≥ {minimum} (决策 3 阈值)"
        ),
    )
    # Decision 3 cross-era binding: 2011 mandatory echoes
    # must reference 2008; 2024 must reference 2008 + 2011.
    # The "reference" is identified by either the echo
    # id, description, trigger, or target_scenes
    # mentioning the prior era's scene_id (or the era
    # number "2008" / "2011").
    if scene_id == "farewell_2011":
        has_2008_ref = any(
            "2008" in (m.get("id", "") + m.get("description", "")
                        + m.get("trigger", ""))
            or "photo_lab_2008" in (m.get("target_scenes") or [])
            for m in mandatory
        )
        _add_check(
            report,
            check_id="contract.farewell_references_2008",
            label="Farewell 2011 引用 2008",
            passed=has_2008_ref,
            detail=(
                "farewell_2011 至少 1 个 mandatory echo 必须引用 2008 (决策 3)"
            ),
        )
    if scene_id == "reunion_2024":
        has_2008 = any(
            "2008" in (m.get("id", "") + m.get("description", "")
                        + m.get("trigger", ""))
            or "photo_lab_2008" in (m.get("target_scenes") or [])
            for m in mandatory
        )
        has_2011 = any(
            "2011" in (m.get("id", "") + m.get("description", "")
                        + m.get("trigger", ""))
            or "farewell_2011" in (m.get("target_scenes") or [])
            for m in mandatory
        )
        _add_check(
            report,
            check_id="contract.reunion_references_2008",
            label="Reunion 2024 引用 2008",
            passed=has_2008,
            detail="reunion_2024 至少 1 个 mandatory echo 必须引用 2008",
        )
        _add_check(
            report,
            check_id="contract.reunion_references_2011",
            label="Reunion 2024 引用 2011",
            passed=has_2011,
            detail="reunion_2024 至少 1 个 mandatory echo 必须引用 2011",
        )
    # Decision 1 — at least 1 mandatory echo per scene
    # should have a non-empty trigger so the AI director
    # knows when to raise it.
    triggers_missing = [m.get("id") for m in mandatory if not m.get("trigger")]
    _add_check(
        report,
        check_id="contract.mandatory_echo_trigger_present",
        label="每个 mandatory echo 都有 trigger",
        passed=not triggers_missing,
        detail=(
            "全部 mandatory echo 都有 trigger 描述: OK"
            if not triggers_missing
            else f"缺失 trigger: {triggers_missing}"
        ),
    )
    # 5 句台词 — if the scene has a candidate_lines block,
    # make sure there are at least 5 lines.
    for echo in mandatory:
        cands = echo.get("candidate_lines") or []
        if cands:
            _add_check(
                report,
                check_id=f"contract.candidate_lines_count.{echo.get('id', 'unknown')}",
                label=f"5 句候选台词 ({echo.get('id')})",
                passed=len(cands) >= 5,
                detail=(
                    f"{echo.get('id')}: {len(cands)} 条 candidate_lines, ≥ 5"
                ),
            )
    # Decision 1 — at least 1 irreversible action
    # (destroy / conceal / give / promise) must be allowed
    # in the scene's ``allowed_actions``.
    allowed = set(doc.get("allowed_actions", []) or [])
    irreversible = {"destroy", "conceal", "give", "promise"}
    has_irrev = bool(allowed & irreversible)
    _add_check(
        report,
        check_id="contract.has_irreversible_action",
        label="至少 1 个不可撤回动作 (决策 1)",
        passed=has_irrev,
        detail=(
            f"allowed_actions ∩ {{destroy, conceal, give, promise}}: "
            f"{sorted(allowed & irreversible) or '空'}"
        ),
    )
    # Decision 1 — at least 6 structured action types
    _add_check(
        report,
        check_id="contract.min_action_types",
        label="≥ 6 个结构化动作 (决策 1)",
        passed=len(allowed) >= 6,
        detail=f"allowed_actions 有 {len(allowed)} 个, ≥ 6",
    )
    return summary


# ---------------------------------------------------------------------------
# Suggestions (non-blocking)
# ---------------------------------------------------------------------------


def _generate_suggestions(
    report: WorkshopReport, doc: dict[str, Any],
) -> None:
    """Add non-blocking suggestions.

    Suggestions are **advisory only**.  They do not
    change :attr:`overall`; they show up in the UI as
    light grey hints.
    """

    if not doc.get("forbidden_reveals"):
        report.suggestions.append(
            "考虑为场景显式声明 forbidden_reveals（防 NPC 提前泄露）"
        )
    if not doc.get("legal_endings"):
        report.suggestions.append(
            "legal_endings 为空 — 至少声明 1 个终止条件"
        )
    mandatory = _extract_mandatory_echoes(doc)
    if any(not m.get("ai_director_must_invoke") for m in mandatory):
        report.suggestions.append(
            "部分 mandatory echo 未设 ai_director_must_invoke — "
            "若希望导演必触发，请显式置 true"
        )


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def validate_file(path: Path) -> WorkshopReport:
    """Validate ``path`` without writing back to disk.

    The report is the *complete* workshop report — the
    caller can render it however they like.
    """

    report = WorkshopReport(
        document_path=str(path),
        document_kind="unknown",
        overall=CheckVerdict.PASS,
    )
    if not path.is_file():
        _add_check(
            report,
            check_id="file.exists",
            label="文件存在",
            passed=False,
            detail=f"找不到文件: {path}",
        )
        report.overall = CheckVerdict.BLOCK
        return report
    if yaml is None:  # pragma: no cover
        _add_check(
            report,
            check_id="yaml.available",
            label="PyYAML 已安装",
            passed=False,
            detail="PyYAML not installed; pip install pyyaml",
        )
        report.overall = CheckVerdict.BLOCK
        return report
    try:
        text = path.read_text(encoding="utf-8")
        doc = yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as exc:
        _add_check(
            report,
            check_id="yaml.parse",
            label="YAML 解析",
            passed=False,
            detail=f"YAML 解析失败: {exc}",
        )
        report.overall = CheckVerdict.BLOCK
        return report
    if not isinstance(doc, dict):
        _add_check(
            report,
            check_id="yaml.shape",
            label="文档类型",
            passed=False,
            detail=f"期望 dict, 实际 {type(doc).__name__}",
        )
        report.overall = CheckVerdict.BLOCK
        return report
    report.document_kind = "scene_contract" if "scene_id" in doc else "interaction"
    # 1) The 4-questions guard (decision 6)
    _run_four_questions(report, doc)
    # 2) The narrative contract validation (decisions 1+3)
    contract_summary = _validate_narrative_contract(report, doc)
    report.contract_summary = contract_summary
    # 3) Suggestions
    _generate_suggestions(report, doc)
    # Final: if any BLOCK was recorded, overall = BLOCK.
    if any(c.verdict is CheckVerdict.BLOCK for c in report.checks):
        report.overall = CheckVerdict.BLOCK
    return report


def upload_file(
    path: Path,
    *,
    new_text: str | None = None,
    hot_reload: bool = False,
) -> WorkshopReport:
    """Validate ``path`` (or ``new_text``) → write to disk → optional hot-reload.

    The function **does not bypass** the 4-questions
    guard.  If the report is BLOCK, ``uploaded`` is
    ``False`` and the file is not written.  This is the
    W10 红线 "不要让内容工坊让策划绕过 mandatory echo
    校验".
    """

    if new_text is not None:
        # Validate the in-memory text by writing to a
        # temporary side path, then validating that path.
        tmp = path.with_suffix(path.suffix + ".incoming")
        tmp.write_text(new_text, encoding="utf-8")
        try:
            report = validate_file(tmp)
        finally:
            if tmp.exists():
                tmp.unlink()
        if report.overall is not CheckVerdict.BLOCK:
            path.write_text(new_text, encoding="utf-8")
            report.written = True
            if hot_reload and _SCENE_LOADER_OK and SceneContractLoader is not None:
                loader = get_default_loader()
                evicted = loader.reload(report.contract_summary.get("sceneId"))
                report.hot_reloaded = bool(evicted)
        return report
    # No in-memory text — just validate on disk.
    report = validate_file(path)
    if report.overall is not CheckVerdict.BLOCK and hot_reload:
        if _SCENE_LOADER_OK and SceneContractLoader is not None:
            loader = get_default_loader()
            evicted = loader.reload(report.contract_summary.get("sceneId"))
            report.hot_reloaded = bool(evicted)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_human(report: WorkshopReport) -> None:
    if report.overall is CheckVerdict.PASS:
        sys.stderr.write(f"✅ {report.document_path}: 通过\n")
    elif report.overall is CheckVerdict.BLOCK:
        sys.stderr.write(f"❌ {report.document_path}: 阻断\n")
    else:
        sys.stderr.write(f"↩  {report.document_path}: skip\n")
    for c in report.checks:
        icon = {
            CheckVerdict.PASS: "✅",
            CheckVerdict.BLOCK: "❌",
            CheckVerdict.SKIP: "↩ ",
        }.get(c.verdict, "?")
        sys.stderr.write(f"  {icon} [{c.check_id}] {c.label}: {c.detail}\n")
    if report.blocking_reasons:
        sys.stderr.write("\n阻断原因:\n")
        for r in report.blocking_reasons:
            sys.stderr.write(f"  - {r}\n")
    if report.suggestions:
        sys.stderr.write("\n建议（非阻断）:\n")
        for s in report.suggestions:
            sys.stderr.write(f"  · {s}\n")
    if report.written:
        sys.stderr.write("\n已写盘。\n")
    if report.hot_reloaded:
        sys.stderr.write("已 hot-reload（不重启服务）。\n")


def _list_yaml_files(case: str | None = None) -> list[Path]:
    root = _PROJECT_ROOT / "content"
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    cases = [case] if case else None
    for case_dir in sorted(root.iterdir()):
        if not case_dir.is_dir():
            continue
        if cases and case_dir.name not in cases:
            continue
        for sub in ("scenes", "recaps", "characters", "beliefs"):
            d = case_dir / sub
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.yaml")):
                candidates.append(p)
            for p in sorted(d.glob("*.yml")):
                candidates.append(p)
    return candidates


def _cmd_validate(args: argparse.Namespace) -> int:
    target = Path(args.path).resolve()
    report = validate_file(target)
    _print_human(report)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.overall is CheckVerdict.PASS else 1


def _cmd_upload(args: argparse.Namespace) -> int:
    target = Path(args.path).resolve()
    if args.from_stdin:
        new_text = sys.stdin.read()
    else:
        new_text = None
    report = upload_file(
        target, new_text=new_text, hot_reload=args.hot_reload,
    )
    _print_human(report)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.overall is CheckVerdict.PASS else 1


def _cmd_status(_args: argparse.Namespace) -> int:
    if not _SCENE_LOADER_OK:
        print(json.dumps({"status": "scene_loader_unavailable"}, ensure_ascii=False))
        return 1
    loader = get_default_loader()
    cached = [sid for sid in SCENES_IN_ORDER if loader.is_cached(sid)]
    print(json.dumps({
        "status": "ok",
        "scenesCached": cached,
        "scenesInOrder": SCENES_IN_ORDER,
        "contentRoot": str(loader.content_root),
    }, ensure_ascii=False, indent=2))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    files = _list_yaml_files(args.case)
    if args.json:
        print(json.dumps(
            [str(p.relative_to(_PROJECT_ROOT)) for p in files],
            ensure_ascii=False, indent=2,
        ))
        return 0
    for p in files:
        sys.stdout.write(f"{p.relative_to(_PROJECT_ROOT)}\n")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    """Scan a case for any blocking YAML files."""

    files = _list_yaml_files(args.case)
    blocked: list[str] = []
    passed: list[str] = []
    for p in files:
        r = validate_file(p)
        if r.overall is CheckVerdict.BLOCK:
            blocked.append(str(p.relative_to(_PROJECT_ROOT)))
        else:
            passed.append(str(p.relative_to(_PROJECT_ROOT)))
    print(json.dumps({
        "passed": passed,
        "blocked": blocked,
    }, ensure_ascii=False, indent=2))
    return 1 if blocked else 0


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="content-workshop",
        description="革命街 AI 原生 · 内容工坊 (策划后台)",
    )
    sub = p.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="JSON-only 输出")

    pv = sub.add_parser("validate", parents=[common], help="校验一个 YAML")
    pv.add_argument("path", help="YAML 路径")
    pv.set_defaults(func=_cmd_validate)

    pu = sub.add_parser("upload", parents=[common], help="上传/写盘一个 YAML")
    pu.add_argument("path", help="YAML 路径")
    pu.add_argument(
        "--from-stdin", action="store_true",
        help="从 stdin 读 YAML 内容（用于 SPA 提交）",
    )
    pu.add_argument(
        "--hot-reload", action="store_true",
        help="校验通过后 hot-reload scene_loader 缓存",
    )
    pu.set_defaults(func=_cmd_upload)

    pl = sub.add_parser("list", parents=[common], help="列出所有可校验的 YAML")
    pl.add_argument("--case", default=None, help="case 过滤 (如 case_01_revolution_street)")
    pl.set_defaults(func=_cmd_list)

    ps = sub.add_parser("status", parents=[common], help="查看 hot-reload 状态")
    ps.set_defaults(func=_cmd_status)

    psc = sub.add_parser("scan", parents=[common], help="扫描一个 case 找阻断的 YAML")
    psc.add_argument("--case", default=None, help="case 过滤")
    psc.set_defaults(func=_cmd_scan)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
