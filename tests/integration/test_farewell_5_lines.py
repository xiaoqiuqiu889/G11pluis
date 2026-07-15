"""W11-B farewell_2011 5 句备选统一 + 决策 2 补充条款落地测试。

Goal
----
验证 UP-20260715-015（farewell_2011 缺 5 句备选 → 设计模式未统一）的落地：
1. farewell_2011.yaml 的 ``mandatory_echoes`` 列表新增
   ``admit_1985_behaviors_5_candidate_lines``，包含 5 句备选台词 + selection_rule。
2. reunion_2024.yaml 的 ``first_words_admit_2008_2011`` 5 句备选与
   farewell_2011 设计模式统一（line_id / text / speaker / seed_id / priority 字段）。
3. photo_lab_2008.yaml 的 ``mandatory_echoes`` 列表新增
   ``admit_2008_behaviors_5_candidate_lines``，包含 5 句备选台词 + selection_rule。
4. narrative_contract.schema.json 加 ``mandatory_echoes`` + ``candidate_lines`` 字段。
5. requirements-review-v1.md 决策 2 补充条款落地（视角付费解锁后第一句台词
   必须引用 player 1985/2008 行为）。

约束
----
* 3 scene 5 句备选**设计模式统一**——结构、字段、selection_rule、red_line 一致。
* 5 句备选必须有 unique line_id / unique seed_id / priority 1-5。
* 5 句台词不能"自由发挥"——NPC Agent 必须按 selection_rule 兜底。
* 红线：不要让 farewell_2011 与 reunion_2024 设计模式不同。
* 红线：不要让 mandatory echo 缺失。
* 红线：不修改 6 个决策（决策 2 补充条款不算改决策——只是文档化）。

This file is the integration test for the W11-B 任务
(D:/G1-ai-native/docs/design/w11-b-farewell-5lines-report.md).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# --- path setup ------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))


# ===========================================================================
# Constants — bind to the project's hard red lines + W11-B brief
# ===========================================================================


SCENES_DIR = _PROJECT_ROOT / "content/case_01_revolution_street/scenes"
SCHEMA_PATH = _PROJECT_ROOT / "server/config/schemas/narrative_contract.schema.json"
REQ_REVIEW_PATH = _PROJECT_ROOT / "docs/design/requirements-review-v1.md"

# Per-scene mandatory echo that carries 5 candidate_lines + selection_rule.
# Each scene has EXACTLY ONE such echo (设计模式统一).
FIVE_LINE_ECHOES = {
    "photo_lab_2008": "admit_2008_behaviors_5_candidate_lines",
    "farewell_2011": "admit_1985_behaviors_5_candidate_lines",
    "reunion_2024": "first_words_admit_2008_2011",
}

# Per-scene fallback (line_01) the selection_rule MUST use when no
# candidate matches the player's triggered seeds.
LINE_01_FALLBACK = {
    "photo_lab_2008": "line_01_photo_in_pocket",
    "farewell_2011": "line_01_walkman_in_pocket_1985",
    "reunion_2024": "line_01_photo_in_pocket",
}

# Required fields on every candidate_line (UP-20260715-015 unified schema).
REQUIRED_LINE_FIELDS = {
    "line_id", "text", "speaker", "seed_id", "priority",
}

# Optional fields allowed on a candidate_line (kept for cross-era aliasing).
OPTIONAL_LINE_FIELDS = {
    "referenced_seed",
    "referenced_1985_seed",
    "referenced_2008_seed",
    "referenced_2011_seed",
}

# selection_rule required sub-fields.
REQUIRED_SELECTION_RULE_FIELDS = {"algorithm", "red_line"}

# Decision-2 supplementary clause anchor (must appear in requirements-review-v1.md).
DECISION_2_SUPPLEMENTARY_CLAUSE = (
    "视角付费解锁后第一句台词必须引用 player 1985/2008 行为"
)

# Decision-2 supplementary clause 3-scene pairing (echo ids in
# requirements-review-v1.md must list all three).
DECISION_2_ECHO_IDS = [
    "admit_2008_behaviors_5_candidate_lines",
    "admit_1985_behaviors_5_candidate_lines",
    "first_words_admit_2008_2011",
]


# ===========================================================================
# Loader helpers
# ===========================================================================


def _load_yaml(path: Path) -> dict:
    """Load a UTF-8 YAML file. PyYAML is the only required dep."""
    import yaml
    with open(path, "r", encoding="utf-8") as fp:
        return yaml.safe_load(fp)


def _load_json(path: Path) -> dict:
    """Load a UTF-8 JSON file."""
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def _load_text(path: Path) -> str:
    """Load a UTF-8 text file."""
    with open(path, "r", encoding="utf-8") as fp:
        return fp.read()


def _scene_yaml_path(scene_id: str) -> Path:
    return SCENES_DIR / f"{scene_id}.yaml"


# ===========================================================================
# Shared assertions on a single 5-line echo
# ===========================================================================


def _assert_candidate_lines_unified(
    test: unittest.TestCase,
    *,
    scene_id: str,
    scene_yaml: dict,
    expected_echo_id: str,
) -> list[dict]:
    """Run the per-echo invariants for a single scene.  Returns the lines.

    Invariants asserted:
    1. The scene has ``mandatory_echoes`` list and the expected echo id
       is present.
    2. The echo carries ``candidate_lines`` (5 lines).
    3. Each line has the required fields: line_id, text, speaker,
       seed_id, priority.  No extra unrecognised fields.
    4. line_id and seed_id are unique across the 5 lines.
    5. priority values are exactly 1..5.
    6. speaker is one of {arash, leila}.
    7. The echo carries a ``selection_rule`` with algorithm + red_line.
    8. The selection_rule's red_line forbids AI 导演 free-form creation.
    9. The selection_rule's algorithm mentions priority ordering + fallback.
    10. There is a line whose line_id equals the scene's line_01 fallback.
    """

    me_list = scene_yaml.get("mandatory_echoes") or []
    me_ids = [me["id"] for me in me_list if isinstance(me, dict)]
    test.assertIn(
        expected_echo_id, me_ids,
        f"{scene_id}.yaml: mandatory_echoes must include {expected_echo_id!r}; "
        f"got {me_ids}"
    )
    echo = next(me for me in me_list if me["id"] == expected_echo_id)

    # ----- 2. candidate_lines has 5 entries -----
    test.assertIn(
        "candidate_lines", echo,
        f"{scene_id}.{expected_echo_id}: must carry candidate_lines"
    )
    lines = echo["candidate_lines"]
    test.assertIsInstance(
        lines, list, f"{scene_id}: candidate_lines must be a list"
    )
    test.assertEqual(
        len(lines), 5,
        f"{scene_id}.{expected_echo_id}: must have exactly 5 candidate_lines; "
        f"got {len(lines)}"
    )

    # ----- 3. required fields present, no extras -----
    allowed_fields = REQUIRED_LINE_FIELDS | OPTIONAL_LINE_FIELDS
    for i, line in enumerate(lines):
        test.assertIsInstance(
            line, dict, f"{scene_id}.lines[{i}] must be a dict"
        )
        keys = set(line.keys())
        missing = REQUIRED_LINE_FIELDS - keys
        test.assertEqual(
            missing, set(),
            f"{scene_id}.lines[{i}]: missing required fields {missing}; "
            f"got keys={sorted(keys)}"
        )
        extra = keys - allowed_fields
        test.assertEqual(
            extra, set(),
            f"{scene_id}.lines[{i}]: unrecognised fields {extra}; "
            f"allowed={sorted(allowed_fields)}"
        )
        # ----- 6. speaker is one of {arash, leila} -----
        test.assertIn(
            line["speaker"], {"arash", "leila"},
            f"{scene_id}.lines[{i}].speaker must be arash|leila; "
            f"got {line['speaker']!r}"
        )

    # ----- 4. uniqueness -----
    line_ids = [ln["line_id"] for ln in lines]
    test.assertEqual(
        len(set(line_ids)), 5,
        f"{scene_id}: line_id must be unique; got {line_ids}"
    )
    seed_ids = [ln["seed_id"] for ln in lines]
    test.assertEqual(
        len(set(seed_ids)), 5,
        f"{scene_id}: seed_id must be unique; got {seed_ids}"
    )
    # seed_id and referenced_seed (if present) should match per line.
    for i, ln in enumerate(lines):
        if "referenced_seed" in ln:
            test.assertEqual(
                ln["referenced_seed"], ln["seed_id"],
                f"{scene_id}.lines[{i}]: seed_id and referenced_seed must "
                f"match (per UP-20260715-015 unified schema); "
                f"got seed_id={ln['seed_id']!r} referenced_seed="
                f"{ln['referenced_seed']!r}"
            )

    # ----- 5. priority 1..5 -----
    priorities = sorted(ln["priority"] for ln in lines)
    test.assertEqual(
        priorities, [1, 2, 3, 4, 5],
        f"{scene_id}: priority must be 1..5 (1=highest); got {priorities}"
    )

    # ----- 7. selection_rule present + has algorithm + red_line -----
    test.assertIn(
        "selection_rule", echo,
        f"{scene_id}.{expected_echo_id}: must carry selection_rule "
        "(UP-20260715-015 red line)"
    )
    rule = echo["selection_rule"]
    rule_keys = set(rule.keys())
    missing_rule = REQUIRED_SELECTION_RULE_FIELDS - rule_keys
    test.assertEqual(
        missing_rule, set(),
        f"{scene_id}.selection_rule: missing required fields {missing_rule}; "
        f"got keys={sorted(rule_keys)}"
    )

    # ----- 8. red_line forbids AI 导演 free-form creation -----
    # Convention: red_line must mention 'candidate_lines' (to forbid
    # creation outside the list) AND use a prohibitive verb (不得 / 禁止).
    # The exact phrasing can vary per scene but the keywords are stable.
    red_line = rule["red_line"]
    test.assertIn(
        "candidate_lines", red_line,
        f"{scene_id}.selection_rule.red_line must mention 'candidate_lines' "
        f"to forbid AI 导演 free-form creation; got: {red_line!r}"
    )
    # At least one prohibitive marker must appear (red_line's
    # vocabulary can be "不得" or "禁止" — both are accepted).
    has_prohibition = any(
        marker in red_line for marker in ("不得", "禁止", "不允许", "不可")
    )
    test.assertTrue(
        has_prohibition,
        f"{scene_id}.selection_rule.red_line must include a prohibitive "
        f"marker (不得/禁止/不允许/不可) to forbid free-form creation; "
        f"got: {red_line!r}"
    )

    # ----- 9. algorithm mentions priority + fallback -----
    algorithm = rule["algorithm"]
    test.assertIn(
        "priority", algorithm.lower() or algorithm,
        f"{scene_id}.selection_rule.algorithm must mention 'priority'"
    )
    test.assertIn(
        "line_01", algorithm,
        f"{scene_id}.selection_rule.algorithm must mention 'line_01' fallback"
    )
    test.assertIn(
        "兜底", algorithm,
        f"{scene_id}.selection_rule.algorithm must mention '兜底' (fallback)"
    )

    # ----- 10. line_01 fallback exists -----
    expected_line_01 = LINE_01_FALLBACK[scene_id]
    test.assertIn(
        expected_line_01, line_ids,
        f"{scene_id}: line_01 fallback {expected_line_01!r} must exist in "
        f"the 5 candidate_lines; got line_ids={line_ids}"
    )

    return lines


# ===========================================================================
# Test cases
# ===========================================================================


class W11BFiveLineUnificationTest(unittest.TestCase):
    """W11-B 5 句备选统一 + 决策 2 补充条款落地 — 集成测试。

    测试矩阵（5 件事）：

    | # | 测试方法 | 验证对象 |
    |---|---|---|
    | 1 | test_farewell_2011_has_5_lines | farewell_2011.yaml 的 5 句备选 + selection_rule |
    | 2 | test_photo_lab_2008_has_5_lines | photo_lab_2008.yaml 的 5 句备选 + selection_rule |
    | 3 | test_reunion_2024_has_5_lines | reunion_2024.yaml 的 5 句备选（已 W4 跑通，验证对齐）|
    | 4 | test_three_scenes_5_lines_design_pattern_unified | 3 scene 设计模式统一 |
    | 5 | test_schema_and_decision_2_supplementary | schema 字段 + 决策 2 补充条款 |
    """

    # -------------------------------------------------------------------
    # shared fixtures
    # -------------------------------------------------------------------

    def setUp(self) -> None:
        self.photo_lab = _load_yaml(_scene_yaml_path("photo_lab_2008"))
        self.farewell = _load_yaml(_scene_yaml_path("farewell_2011"))
        self.reunion = _load_yaml(_scene_yaml_path("reunion_2024"))
        self.schema = _load_json(SCHEMA_PATH)
        self.req_review = _load_text(REQ_REVIEW_PATH)

    # ==================================================================
    # Test 1: farewell_2011 has 5 candidate_lines
    # ==================================================================

    def test_farewell_2011_has_5_lines(self) -> None:
        """UP-20260715-015：farewell_2011 5 句备选 + selection_rule 必须存在。

        farewell_2011 的 mandatory echo ``admit_1985_behaviors_5_candidate_lines``
        对应 UP-20260715-015 + 决策 2 补充条款。

        5 句台词对应 5 个 1985/1986/1989 行为种子（player 1985 行为）：
          - walkman_in_pocket_1985
          - postcard_moscow_vienna
          - grip_then_release_1985
          - chocolate_wrapper_1986
          - arrival_postcard_1989
        """

        lines = _assert_candidate_lines_unified(
            self,
            scene_id="farewell_2011",
            scene_yaml=self.farewell,
            expected_echo_id=FIVE_LINE_ECHOES["farewell_2011"],
        )

        # Verify the 5 seed_ids match the UP-20260715-015 brief.
        expected_seeds = {
            "walkman_in_pocket_1985",
            "postcard_moscow_vienna",
            "grip_then_release_1985",
            "chocolate_wrapper_1986",
            "arrival_postcard_1989",
        }
        actual_seeds = {ln["seed_id"] for ln in lines}
        self.assertEqual(
            actual_seeds, expected_seeds,
            f"farewell_2011: 5 seed_ids must match the UP-20260715-015 brief; "
            f"got {actual_seeds}, expected {expected_seeds}"
        )

        # Verify the speakers match the brief (3 arash + 2 leila).
        speakers = [ln["speaker"] for ln in lines]
        self.assertEqual(
            sorted(speakers.count(s) for s in ("arash", "leila")),
            [2, 3],
            f"farewell_2011: speaker distribution must be 3 arash + 2 leila; "
            f"got {speakers}"
        )

        # priority 1 + 2 are arash (walkman + postcard per brief).
        p1 = next(ln for ln in lines if ln["priority"] == 1)
        p2 = next(ln for ln in lines if ln["priority"] == 2)
        self.assertEqual(p1["speaker"], "arash")
        self.assertEqual(p2["speaker"], "arash")

        # priority 3 + 4 are leila (grip + chocolate per brief).
        p3 = next(ln for ln in lines if ln["priority"] == 3)
        p4 = next(ln for ln in lines if ln["priority"] == 4)
        self.assertEqual(p3["speaker"], "leila")
        self.assertEqual(p4["speaker"], "leila")

        # priority 5 is arash (arrival postcard per brief).
        p5 = next(ln for ln in lines if ln["priority"] == 5)
        self.assertEqual(p5["speaker"], "arash")

    # ==================================================================
    # Test 2: photo_lab_2008 has 5 candidate_lines
    # ==================================================================

    def test_photo_lab_2008_has_5_lines(self) -> None:
        """3 scene 5 句备选统一：photo_lab_2008 也必须有 5 句备选 + selection_rule。

        photo_lab_2008 的 mandatory echo ``admit_2008_behaviors_5_candidate_lines``
        对应 5 个 2008 行为种子（player 2008 行为）：
          - photo_in_pocket
          - photo_in_book
          - grip_then_release
          - poem_in_toolbox
          - date_written_on_back
        """

        lines = _assert_candidate_lines_unified(
            self,
            scene_id="photo_lab_2008",
            scene_yaml=self.photo_lab,
            expected_echo_id=FIVE_LINE_ECHOES["photo_lab_2008"],
        )

        # Verify the 5 seed_ids match the brief.
        expected_seeds = {
            "photo_in_pocket",
            "photo_in_book",
            "grip_then_release",
            "poem_in_toolbox",
            "date_written_on_back",
        }
        actual_seeds = {ln["seed_id"] for ln in lines}
        self.assertEqual(
            actual_seeds, expected_seeds,
            f"photo_lab_2008: 5 seed_ids must match the brief; "
            f"got {actual_seeds}, expected {expected_seeds}"
        )

    # ==================================================================
    # Test 3: reunion_2024 has 5 candidate_lines (already W4, verify alignment)
    # ==================================================================

    def test_reunion_2024_has_5_lines(self) -> None:
        """reunion_2024 已在 W4-Content-Update 跑通，本任务只做设计模式对齐验证。

        reunion_2024 的 mandatory echo ``first_words_admit_2008_2011``
        对应 5 个跨年代（2008 + 2011）行为种子：
          - 3 × 2008 seed: photo_in_pocket, photo_in_book, grip_then_release
          - 2 × 2011 seed: bus_ticket_pair_unused, i_arrived_text
        """

        lines = _assert_candidate_lines_unified(
            self,
            scene_id="reunion_2024",
            scene_yaml=self.reunion,
            expected_echo_id=FIVE_LINE_ECHOES["reunion_2024"],
        )

        # Verify the 5 seed_ids match the W4 brief (3 × 2008 + 2 × 2011).
        expected_seeds = {
            "photo_in_pocket",
            "photo_in_book",
            "grip_then_release",
            "bus_ticket_pair_unused",
            "i_arrived_text",
        }
        actual_seeds = {ln["seed_id"] for ln in lines}
        self.assertEqual(
            actual_seeds, expected_seeds,
            f"reunion_2024: 5 seed_ids must match the W4 brief; "
            f"got {actual_seeds}, expected {expected_seeds}"
        )

        # Verify cross-era coverage (决策 3 + 决策 1 配套约束).
        era_2008_seeds = {"photo_in_pocket", "photo_in_book",
                          "grip_then_release"}
        era_2011_seeds = {"bus_ticket_pair_unused", "i_arrived_text"}
        self.assertTrue(
            era_2008_seeds.issubset(actual_seeds),
            f"reunion_2024: 3 of 5 lines must reference 2008 seeds; "
            f"missing: {era_2008_seeds - actual_seeds}"
        )
        self.assertTrue(
            era_2011_seeds.issubset(actual_seeds),
            f"reunion_2024: 2 of 5 lines must reference 2011 seeds; "
            f"missing: {era_2011_seeds - actual_seeds}"
        )

    # ==================================================================
    # Test 4: 3 scene 5 句备选 design pattern unified
    # ==================================================================

    def test_three_scenes_5_lines_design_pattern_unified(self) -> None:
        """W11-B 红线：3 scene 5 句备选**设计模式统一**——结构、字段、
        selection_rule、red_line 一致。

        这个测试是「统一性」的总闸门：3 scene 同时存在 + 同结构 + 同字段集 +
        同 selection_rule 形态 + 同 red_line 措辞。
        """

        unified_lines: dict[str, list[dict]] = {}
        unified_rules: dict[str, dict] = {}

        for scene_id, echo_id in FIVE_LINE_ECHOES.items():
            scene_yaml = getattr(self, {
                "photo_lab_2008": "photo_lab",
                "farewell_2011": "farewell",
                "reunion_2024": "reunion",
            }[scene_id])
            me_list = scene_yaml["mandatory_echoes"]
            echo = next(me for me in me_list if me["id"] == echo_id)
            unified_lines[scene_id] = echo["candidate_lines"]
            unified_rules[scene_id] = echo["selection_rule"]

        # ----- A. All 3 scenes have exactly 5 lines -----
        for scene_id, lines in unified_lines.items():
            self.assertEqual(
                len(lines), 5,
                f"{scene_id}: must have 5 candidate_lines (设计模式统一); "
                f"got {len(lines)}"
            )

        # ----- B. Required fields are identical across the 3 scenes -----
        # 设计模式统一约束：
        # - 3 scene 的 **required** 字段集必须完全相同（必含
        #   {line_id, text, speaker, seed_id, priority}）
        # - 3 scene 的 **optional** 字段集可以不同（每个场景的
        #   era-anchored 字段——referenced_1985_seed / referenced_2008_seed /
        #   referenced_2011_seed——按场景所属时代而不同），但所有
        #   optional 字段必须在白名单内
        per_scene_required_keys: dict[str, set[str]] = {}
        per_scene_optional_keys: dict[str, set[str]] = {}
        for scene_id, lines in unified_lines.items():
            keys_per_line = [set(ln.keys()) for ln in lines]
            scene_keys = set().union(*keys_per_line)
            required = scene_keys & REQUIRED_LINE_FIELDS
            optional = scene_keys - REQUIRED_LINE_FIELDS
            self.assertEqual(
                required, REQUIRED_LINE_FIELDS,
                f"{scene_id}: required fields must be exactly "
                f"{REQUIRED_LINE_FIELDS}; got {required}"
            )
            self.assertTrue(
                optional.issubset(OPTIONAL_LINE_FIELDS),
                f"{scene_id}: optional fields must be in "
                f"{OPTIONAL_LINE_FIELDS}; got {optional}"
            )
            per_scene_required_keys[scene_id] = required
            per_scene_optional_keys[scene_id] = optional

        # All 3 scenes must have the SAME required field set (设计模式统一).
        unique_required_key_sets = set(
            frozenset(ks) for ks in per_scene_required_keys.values()
        )
        self.assertEqual(
            len(unique_required_key_sets), 1,
            f"3 scene must have identical required candidate_line fields "
            f"(设计模式统一); got {per_scene_required_keys}"
        )

        # Every scene must have at least one era-anchored alias for
        # cross-era traceability (referenced_seed is the
        # minimum-compat alias).
        for scene_id, opt in per_scene_optional_keys.items():
            self.assertIn(
                "referenced_seed", opt,
                f"{scene_id}: must include 'referenced_seed' (the compat "
                f"alias of seed_id, kept for W4 reunion_2024 schema compat); "
                f"got optional fields {opt}"
            )

        # ----- C. selection_rule is structurally identical -----
        for scene_id, rule in unified_rules.items():
            self.assertEqual(
                set(rule.keys()), REQUIRED_SELECTION_RULE_FIELDS,
                f"{scene_id}: selection_rule must have exactly "
                f"{REQUIRED_SELECTION_RULE_FIELDS}; got {set(rule.keys())}"
            )

        # ----- D. red_line is the SAME Chinese sentence across all 3 scenes -----
        red_lines = {sid: rule["red_line"] for sid, rule in unified_rules.items()}
        unique_red_lines = set(red_lines.values())
        self.assertEqual(
            len(unique_red_lines), 1,
            f"3 scene red_line must be the SAME sentence (设计模式统一); "
            f"got {red_lines}"
        )
        self.assertIn(
            "candidate_lines", next(iter(unique_red_lines)),
            "red_line must mention 'candidate_lines' (forbids AI 导演 free-form)"
        )

        # ----- E. priority values are 1..5 in all 3 scenes -----
        for scene_id, lines in unified_lines.items():
            priorities = sorted(ln["priority"] for ln in lines)
            self.assertEqual(
                priorities, [1, 2, 3, 4, 5],
                f"{scene_id}: priority must be 1..5 (1=highest); "
                f"got {priorities}"
            )

        # ----- F. speaker set is arash ∪ leila (no other speakers) -----
        for scene_id, lines in unified_lines.items():
            speakers = {ln["speaker"] for ln in lines}
            self.assertTrue(
                speakers.issubset({"arash", "leila"}),
                f"{scene_id}: speaker must be in {{arash, leila}}; "
                f"got {speakers}"
            )

        # ----- G. line_01 fallback exists in all 3 scenes -----
        for scene_id, lines in unified_lines.items():
            line_ids = [ln["line_id"] for ln in lines]
            self.assertEqual(
                line_ids[0], LINE_01_FALLBACK[scene_id],
                f"{scene_id}: lines[0].line_id must be the documented "
                f"line_01 fallback {LINE_01_FALLBACK[scene_id]!r}; "
                f"got {line_ids[0]!r}"
            )
            # The priority of line_01 must be 1 (highest).
            self.assertEqual(
                lines[0]["priority"], 1,
                f"{scene_id}: lines[0] (line_01) must have priority=1; "
                f"got {lines[0]['priority']}"
            )

    # ==================================================================
    # Test 5: schema + Decision 2 supplementary clause
    # ==================================================================

    def test_schema_and_decision_2_supplementary(self) -> None:
        """schema 加 candidate_lines 字段 + 决策 2 补充条款落地。

        验证:
        1. narrative_contract.schema.json 的 properties 含 ``mandatory_echoes``
        2. mandatory_echoes 内的 items.properties 含 ``candidate_lines`` + 
           ``selection_rule``
        3. candidate_lines.items.required 含 {line_id, text, speaker, seed_id, priority}
        4. selection_rule.required 含 {algorithm, red_line}
        5. requirements-review-v1.md 决策 2 含补充条款原文
        6. requirements-review-v1.md 决策 2 列出 3 个 echo id
        7. requirements-review-v1.md 第 6 节「审批 / 变更记录」含 UP-20260715-015 条目
        """

        # ----- 1. schema: mandatory_echoes in properties -----
        self.assertIn(
            "mandatory_echoes", self.schema["properties"],
            "narrative_contract.schema.json: properties must include "
            "'mandatory_echoes' (UP-20260715-015 schema update)"
        )
        me_schema = self.schema["properties"]["mandatory_echoes"]
        self.assertEqual(
            me_schema["type"], "array",
            "mandatory_echoes must be a JSON array"
        )

        # ----- 2. candidate_lines + selection_rule on each echo item -----
        echo_item_schema = me_schema["items"]
        self.assertIn(
            "properties", echo_item_schema,
            "mandatory_echoes.items must have a 'properties' block"
        )
        echo_props = echo_item_schema["properties"]
        self.assertIn(
            "candidate_lines", echo_props,
            "mandatory_echoes.items.properties must include 'candidate_lines'"
        )
        self.assertIn(
            "selection_rule", echo_props,
            "mandatory_echoes.items.properties must include 'selection_rule'"
        )

        # ----- 3. candidate_lines items have the 5 required fields -----
        cl_schema = echo_props["candidate_lines"]
        self.assertEqual(cl_schema["type"], "array")
        cl_item_schema = cl_schema["items"]
        required_cl_fields = set(cl_item_schema["required"])
        self.assertEqual(
            required_cl_fields, REQUIRED_LINE_FIELDS,
            f"candidate_lines.items.required must be {REQUIRED_LINE_FIELDS}; "
            f"got {required_cl_fields}"
        )
        # speaker must be enum (arash, leila)
        cl_speaker_schema = cl_item_schema["properties"]["speaker"]
        self.assertEqual(
            cl_speaker_schema.get("enum"), ["arash", "leila"],
            "candidate_lines.items.properties.speaker must be enum [arash, leila]"
        )
        # priority must be integer 1..16
        cl_priority_schema = cl_item_schema["properties"]["priority"]
        self.assertEqual(cl_priority_schema["type"], "integer")
        self.assertEqual(cl_priority_schema["minimum"], 1)
        self.assertEqual(cl_priority_schema["maximum"], 16)

        # ----- 4. selection_rule required fields -----
        sr_schema = echo_props["selection_rule"]
        self.assertEqual(
            set(sr_schema["required"]), REQUIRED_SELECTION_RULE_FIELDS,
            f"selection_rule.required must be {REQUIRED_SELECTION_RULE_FIELDS}"
        )

        # ----- 5. Decision 2 supplementary clause present in requirements-review -----
        self.assertIn(
            DECISION_2_SUPPLEMENTARY_CLAUSE, self.req_review,
            f"requirements-review-v1.md: 决策 2 must include the supplementary "
            f"clause {DECISION_2_SUPPLEMENTARY_CLAUSE!r}"
        )

        # ----- 6. Decision 2 lists all 3 echo ids -----
        # Find the 决策 2 section.
        idx_2 = self.req_review.find("### 决策 2")
        self.assertGreater(idx_2, -1, "决策 2 section not found")
        # Slice to the next 决策 3 or end of file.
        idx_3 = self.req_review.find("### 决策 3", idx_2)
        section_2 = self.req_review[idx_2: idx_3 if idx_3 > 0 else None]
        for echo_id in DECISION_2_ECHO_IDS:
            self.assertIn(
                echo_id, section_2,
                f"决策 2 must reference echo_id {echo_id!r} (3-scene 5 句备选统一)"
            )

        # ----- 7. 审批 / 变更记录 has UP-20260715-015 entry -----
        self.assertIn(
            "UP-20260715-015", self.req_review,
            "审批 / 变更记录 must include UP-20260715-015 entry"
        )
        self.assertIn(
            "决策 2 补充条款", self.req_review,
            "审批 / 变更记录 must include '决策 2 补充条款' label"
        )

    # ==================================================================
    # Test 6: runtime smoke — selection_rule returns a deterministic
    #         line_01 fallback when no candidate matches
    # ==================================================================

    def test_selection_rule_fallback_returns_line_01(self) -> None:
        """selection_rule 在无任何 candidate 匹配时必须用 line_01 兜底。

        这是一个轻量的「运行时」冒烟测试，不依赖完整的 resolver
        pipeline——我们只模拟 selection_rule 的核心逻辑。
        """

        def _select(
            candidates: list[dict],
            triggered_seed_ids: set[str],
        ) -> str:
            """Mirror the YAML's selection_rule algorithm in 4 lines."""
            for line in sorted(candidates, key=lambda ln: ln["priority"]):
                if line["seed_id"] in triggered_seed_ids:
                    return line["line_id"]
            return candidates[0]["line_id"]  # line_01 fallback

        for scene_id, scene_yaml in (
            ("photo_lab_2008", self.photo_lab),
            ("farewell_2011", self.farewell),
            ("reunion_2024", self.reunion),
        ):
            echo_id = FIVE_LINE_ECHOES[scene_id]
            echo = next(
                me for me in scene_yaml["mandatory_echoes"]
                if me["id"] == echo_id
            )
            candidates = echo["candidate_lines"]

            # ----- Empty triggered set → line_01 fallback -----
            selected = _select(candidates, triggered_seed_ids=set())
            self.assertEqual(
                selected, LINE_01_FALLBACK[scene_id],
                f"{scene_id}: empty triggered seeds must fall back to line_01 "
                f"({LINE_01_FALLBACK[scene_id]!r}); got {selected!r}"
            )

            # ----- Trigger the highest-priority seed → line_01 selected -----
            line_01_seed = candidates[0]["seed_id"]
            selected = _select(
                candidates, triggered_seed_ids={line_01_seed}
            )
            self.assertEqual(
                selected, candidates[0]["line_id"],
                f"{scene_id}: triggering priority-1 seed must select line_01"
            )

            # ----- Trigger a lower-priority seed → that line is selected -----
            line_03_seed = candidates[2]["seed_id"]
            selected = _select(
                candidates, triggered_seed_ids={line_03_seed}
            )
            self.assertEqual(
                selected, candidates[2]["line_id"],
                f"{scene_id}: triggering priority-3 seed must select line_03"
            )

            # ----- Trigger multiple seeds → lowest-priority (highest-priority
            #       rank) line wins -----
            multi = {candidates[0]["seed_id"], candidates[2]["seed_id"]}
            selected = _select(candidates, triggered_seed_ids=multi)
            self.assertEqual(
                selected, candidates[0]["line_id"],
                f"{scene_id}: multi-trigger picks the highest-priority line; "
                f"got {selected!r}, expected {candidates[0]['line_id']!r}"
            )

    # ==================================================================
    # Test 7: 红线对账 — 6 decisions 完整性
    # ==================================================================

    def test_six_decisions_intact(self) -> None:
        """红线：6 个决策不能改。验证 requirements-review-v1.md 仍然包含全部 6 项。

        决策 2 的修改是「补充条款」性质，不改变原 5 条 bullets 的语义；
        验证 5 个原 bullets 仍然存在。
        """

        for decision_id in (
            "决策 1", "决策 2", "决策 3", "决策 4", "决策 5", "决策 6"
        ):
            self.assertIn(
                f"### {decision_id}", self.req_review,
                f"requirements-review-v1.md: must still contain {decision_id!r}"
            )

        # 决策 2 原 5 条 bullets 必须仍在。
        section_2_start = self.req_review.find("### 决策 2")
        section_3_start = self.req_review.find("### 决策 3", section_2_start)
        section_2 = self.req_review[section_2_start:section_3_start]
        for original_bullet in (
            "默认 = 第三人称旁观者",
            "视角切换 = **付费解锁**",
            "你看到了 X",
            "不是换 UI，是换叙事",
            "暗示",
        ):
            self.assertIn(
                original_bullet, section_2,
                f"决策 2 original bullet {original_bullet!r} must be intact"
            )

        # 决策 1-6 各自的硬约束段必须仍在。
        for keyword in (
            "AI 原生门槛",
            "付费解锁",
            "mandatory echo",
            "BYOK",
            "硬红线",
            "CI 阻断",
        ):
            self.assertIn(
                keyword, self.req_review,
                f"requirements-review-v1.md: must still contain {keyword!r}"
            )


# ===========================================================================
# Module exit
# ===========================================================================


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
