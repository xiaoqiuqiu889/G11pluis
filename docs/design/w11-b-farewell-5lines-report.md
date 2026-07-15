# W11-B farewell_2011 5 句备选统一 + 决策 2 补充条款 · 落地报告

| 项 | 值 |
|---|---|
| 任务 ID | W11-B farewell_2011 5 句备选统一 + 决策 2 补充条款落地 |
| 执行日期 | 2026-07-15 |
| 决策源 | `docs/design/requirements-review-v1.md`（UP-20260715-015 + 决策 2 补充条款） |
| 输入 | farewell_2011.yaml（缺 5 句备选）+ reunion_2024.yaml（W4 已 5 句）+ photo_lab_2008.yaml（缺 5 句）+ narrative_contract.schema.json + requirements-review-v1.md |
| 输出 | 3 scene 5 句备选统一 + schema 加 candidate_lines + 决策 2 补充条款 + 集成测试（7/7）+ guard（3/3 全过）|
| 验证 | guard 3/3 全过（EXITCODE=0，blocking_documents=0）；集成测试 7/7 全过；原回归测试 8/8 全过 |

---

## 0. 摘要

把 UP-20260715-015（farewell_2011 缺 5 句备选 → 设计模式未统一）和决策 2 补充条款（**视角付费解锁后第一句台词必须引用 player 1985/2008 行为**）落地到 3 个 scene + schema + requirements-review + 集成测试。所有红线守住：

- **3 scene 5 句备选设计模式统一**（photo_lab_2008 / farewell_2011 / reunion_2024）
- **farewell_2011 5 句备选补全**（UP-20260715-015）
- **photo_lab_2008 5 句备选补全**（3 scene 统一硬要求）
- **narrative_contract.schema.json 加 `mandatory_echoes` + `candidate_lines` 字段**
- **决策 2 补充条款**追加到 requirements-review-v1.md
- **集成测试 7/7 全过**（含选择规则兜底冒烟）
- **guard 3/3 全过**（3 scene 通过 D_mandatory_echo_declared，exit 0，无 blocking）
- **零回归**：原有 `test_end_to_end_three_scenes.py` 8/8 全过、guard 测试 85/85 全过

未修改 6 个决策（决策 2 补充条款不算改决策——只是文档化补充条款）。未触碰 `_legacy_v6/`。未修改 6 个决策的硬约束段。

---

## 1. UP 决策落地清单

| UP | 状态 | 落地位置 | 备注 |
|---|---|---|---|
| UP-20260715-015 farewell_2011 5 句备选 | ✅ | `farewell_2011.yaml: mandatory_echoes[2]` | 新增 `admit_1985_behaviors_5_candidate_lines`，5 line + selection_rule |
| 3 scene 设计模式统一 | ✅ | `farewell_2011.yaml` + `reunion_2024.yaml`（已 W4 跑通，本任务加 `seed_id` 字段统一）+ `photo_lab_2008.yaml` 新增 `admit_2008_behaviors_5_candidate_lines` | 同一设计模式（line_id/text/speaker/seed_id/priority + selection_rule）跨场景完全对齐 |
| 决策 2 补充条款 | ✅ | `requirements-review-v1.md: 决策 2` + `第 6 节 审批 / 变更记录` | 追加 1 条 bullet：「视角付费解锁后第一句台词必须引用 player 1985/2008 行为」+ 5 句备选 + selection_rule 兜底 |
| schema 加 `candidate_lines` | ✅ | `narrative_contract.schema.json: mandatory_echoes` | 新增 `mandatory_echoes` + `candidate_lines` + `selection_rule` 字段定义 |
| 集成测试 100% 过 | ✅ | `tests/integration/test_farewell_5_lines.py` | 7/7 全过 |

---

## 2. 3 Scene 5 句备选设计模式统一

### 2.1 设计模式契约（UP-20260715-015 统一）

```yaml
# 5 句备选 — 同一结构跨场景
- id: <scene>_admit_<era>_behaviors_5_candidate_lines
  description: ...
  trigger: ...
  target_scenes: [...]
  ai_director_must_invoke: true
  references_<era>: [...]    # era-anchored aliases (per scene)
  ai_director_constraint: "..."
  candidate_lines:           # 5 lines, unique line_id / seed_id / priority 1-5
    - line_id: line_01_<seed>
      text: "..."
      speaker: arash | leila
      seed_id: <seed>
      referenced_seed: <seed>           # compat alias
      referenced_<era>_seed: <seed>     # era-anchored alias (per scene)
      priority: 1..5
    ...
  selection_rule:
    algorithm: |
      1. NPC Agent 拉取玩家本局触发的所有 causal_seed 列表
      2. 对 candidate_lines 按 priority 升序遍历，找到第一个
         seed_id / referenced_seed 在玩家触发列表里的 line
      3. 若多触发：取 priority 最小（即"最触动"）的那条
      4. 若无任何 candidate 匹配：AI 导演必须使用 line_01 兜底
         —— 禁止自由发挥台词
    red_line: "AI 导演不得在 candidate_lines 之外创造台词"
```

**5 句备选结构必须字段**：`{ line_id, text, speaker, seed_id, priority }`
**5 句备选可选字段**（跨场景可不同）：`referenced_seed`, `referenced_1985_seed`, `referenced_2008_seed`, `referenced_2011_seed`

### 2.2 photo_lab_2008 5 句备选（5 个 2008 行为种子）

| priority | line_id | speaker | text | seed_id |
|---:|---|---|---|---|
| 1 | line_01_photo_in_pocket | leila | "我把这一张放进包里……你不会怪我吧？" | photo_in_pocket |
| 2 | line_02_photo_in_book | arash | "这一张我夹进诗集……你替我留着诗吗？" | photo_in_book |
| 3 | line_03_grip_then_release | leila | "我们刚才握了一下手……又松开了" | grip_then_release |
| 4 | line_04_poem_in_toolbox | arash | "你那张折诗我收进工具盒了……别告诉任何人" | poem_in_toolbox |
| 5 | line_05_date_written_on_back | leila | "我在照片背面写了 2008.6.21……你看不看得到" | date_written_on_back |

### 2.3 farewell_2011 5 句备选（5 个 1985/1986/1989 行为种子）

| priority | line_id | speaker | text | seed_id |
|---:|---|---|---|---|
| 1 | line_01_walkman_in_pocket_1985 | arash | "那个 walkman 我一直留着……" | walkman_in_pocket_1985 |
| 2 | line_02_postcard_moscow_vienna | arash | "你 1986 年那张明信片……我从维也纳带过来了" | postcard_moscow_vienna |
| 3 | line_03_grip_then_release_1985 | leila | "你握住又松开……和我们第一次听你弹琴那晚一模一样" | grip_then_release_1985 |
| 4 | line_04_chocolate_wrapper_1986 | leila | "你那两颗松子糖锡纸……我口袋里一直留到现在" | chocolate_wrapper_1986 |
| 5 | line_05_arrival_postcard_1989 | arash | "1989 年那条'我到了'的明信片……我一直贴在琴盖上" | arrival_postcard_1989 |

### 2.4 reunion_2024 5 句备选（已 W4 跑通，本任务加 `seed_id` 字段统一）

| priority | line_id | speaker | text | seed_id |
|---:|---|---|---|---|
| 1 | line_01_photo_in_pocket | arash | "你把那张照片带在身上带了多少年？" | photo_in_pocket |
| 2 | line_02_photo_in_book | arash | "我在诗集里一直留着那张照片……" | photo_in_book |
| 3 | line_03_grip_then_release | arash | "你握住又松开……和那时候一模一样。" | grip_then_release |
| 4 | line_04_bus_ticket_pair | leila | "你那两张 304 公交票……阿拉什你一直留着吗？" | bus_ticket_pair_unused |
| 5 | line_05_i_arrived_text | leila | "2011 年那条'我到了'的短信……我一直存着。" | i_arrived_text |

**W4 已存在的 5 line 结构**：原 W4 报告用 `{line_id, text, speaker, referenced_seed, referenced_2008_seed, referenced_2011_seed, priority}` 7 字段
**W11-B 统一为**：在 W4 基础上加 `seed_id`（与 `referenced_seed` 等价），满足 UP-20260715-015 统一字段集 `{ priority, speaker, text, seed_id }`

### 2.5 跨场景统一验证

| 检查项 | photo_lab_2008 | farewell_2011 | reunion_2024 | 一致？ |
|---|---|---|---|---|
| 5 句备选 | ✅ 5 | ✅ 5 | ✅ 5 | ✅ |
| required 字段集 `{line_id, text, speaker, seed_id, priority}` | ✅ | ✅ | ✅ | ✅ |
| line_id unique | ✅ | ✅ | ✅ | ✅ |
| seed_id unique | ✅ | ✅ | ✅ | ✅ |
| priority 1-5 | ✅ | ✅ | ✅ | ✅ |
| speaker ∈ {arash, leila} | ✅ | ✅ | ✅ | ✅ |
| selection_rule 存在 | ✅ | ✅ | ✅ | ✅ |
| selection_rule.algorithm 含 priority + line_01 + 兜底 | ✅ | ✅ | ✅ | ✅ |
| selection_rule.red_line 含 candidate_lines + 禁止标记 | ✅ | ✅ | ✅ | ✅ |
| line_01 fallback 存在 | ✅ | ✅ | ✅ | ✅ |
| mandatory_echoes ≥ 1 | 3 | 3 | 5 | n/a |

---

## 3. narrative_contract.schema.json 改动明细

### 3.1 新增 `mandatory_echoes` 属性（UP-20260715-015）

```json
"mandatory_echoes": {
  "type": "array",
  "items": {
    "type": "object",
    "additionalProperties": false,
    "required": ["id", "description", "ai_director_must_invoke"],
    "properties": {
      "id": {"type": "string", "minLength": 1, "maxLength": 128},
      "description": {"type": "string", "minLength": 1, "maxLength": 1000},
      "trigger": {"type": "string", "minLength": 1, "maxLength": 1000},
      "target_scenes": {"type": "array", "items": {"type": "string"}, "maxItems": 16},
      "ai_director_must_invoke": {"type": "boolean"},
      "references_1985": {"type": "array", "items": {"type": "string"}, "maxItems": 32},
      "references_2008": {"type": "array", "items": {"type": "string"}, "maxItems": 32},
      "references_2011": {"type": "array", "items": {"type": "string"}, "maxItems": 32},
      "ai_director_constraint": {"type": "string", "minLength": 1, "maxLength": 1000},
      "candidate_lines": {"type": "array", "items": {...}, "minItems": 0, "maxItems": 16},
      "selection_rule": {
        "type": "object",
        "additionalProperties": false,
        "required": ["algorithm", "red_line"],
        "properties": {
          "algorithm": {"type": "string", "minLength": 1, "maxLength": 4000},
          "red_line": {"type": "string", "minLength": 1, "maxLength": 500}
        }
      }
    }
  },
  "minItems": 0,
  "maxItems": 32,
  "description": "Mandatory echoes ... At least one echo is required to carry `candidate_lines` + `selection_rule` when the scene has a 'first words admit' moment (UP-20260715-015 3-scene 5 句备选统一)."
}
```

### 3.2 candidate_lines 形态（统一 5 句备选结构）

```json
"candidate_lines": {
  "type": "array",
  "items": {
    "type": "object",
    "additionalProperties": false,
    "required": ["line_id", "text", "speaker", "seed_id", "priority"],
    "properties": {
      "line_id": {"type": "string", "minLength": 1, "maxLength": 128},
      "text": {"type": "string", "minLength": 1, "maxLength": 500},
      "speaker": {"type": "string", "enum": ["arash", "leila"]},
      "seed_id": {"type": "string", "minLength": 1, "maxLength": 128},
      "referenced_seed": {"type": "string", "minLength": 1, "maxLength": 128},
      "referenced_1985_seed": {"type": "string", "minLength": 1, "maxLength": 128},
      "referenced_2008_seed": {"type": "string", "minLength": 1, "maxLength": 128},
      "referenced_2011_seed": {"type": "string", "minLength": 1, "maxLength": 128},
      "priority": {"type": "integer", "minimum": 1, "maximum": 16}
    }
  },
  "minItems": 0,
  "maxItems": 16
}
```

**Schema 设计决策**：
- `mandatory_echoes` 加到 `properties` 但不加到 `required`——向后兼容（旧合同没有 mandatory_echoes 仍能通过）
- `candidate_lines` `additionalProperties: false`——禁止在 5 句备选上挂任意字段，强制使用统一 schema
- `speaker` 强制 enum（arash/leila）——禁止其他 NPC 候选人
- `priority` 1..16——5 句备选用 1-5，但 schema 留 16 容量给未来的多候选场景
- `referenced_<era>_seed` 三个 era-anchored 别名都为 optional——跨场景可按需选用

---

## 4. requirements-review-v1.md 决策 2 补充条款

### 4.1 决策 2 补充条款内容（追加到 `决策 2: "记忆修复者"的具体体感`）

```yaml
- **# 补充条款（UP-20260715-015 / W11-B）**：
  视角付费解锁后**第一句台词必须引用 player 1985/2008 行为**——
  - 1985/2008 指的是 player 在更早年代的关键行为种子
  - 5 句备选台词对应 5 个跨年代行为种子，按 priority 升序取最触动
  - 落地于 3 个场景的 mandatory echo 统一设计模式：
    - `photo_lab_2008.admit_2008_behaviors_5_candidate_lines`
    - `farewell_2011.admit_1985_behaviors_5_candidate_lines`
    - `reunion_2024.first_words_admit_2008_2011`
  - 候选结构（narrative_contract.schema.json 已加 `candidate_lines`）：
    `{ line_id, text, speaker, seed_id, priority }`（+ era-anchored aliases）
  - selection_rule：NPC Agent 用 `referencedMemoryIds` 自动匹配 causal_seed，
    按 priority 取最触动；无任何 candidate 匹配 → line_01 兜底（**禁自由发挥**）
```

### 4.2 第 6 节 审批 / 变更记录

| 日期 | 决策 | 动作 | 操作人 |
|---|---|---|---|
| 2026-07-14 | 全部 6 项 | 起草、定稿 | Mavis / Mavis 用户 |
| 2026-07-15 | 决策 2 补充条款（UP-20260715-015）| 追加 1 条 bullets：**视角付费解锁后第一句台词必须引用 player 1985/2008 行为**；3 scene 5 句备选设计模式统一；selection_rule 兜底；不影响其他 5 个决策 | Mavis / W11-B session |

### 4.3 红线对账

| 红线 | 状态 | 证据 |
|---|---|---|
| 不修改 6 个决策的硬约束段 | ✅ | 决策 1-5 bullets 完全保留；决策 2 仅追加 1 条补充条款，原 5 条 bullets 100% 保留 |
| 决策 2 补充条款不算改决策 | ✅ | 补充条款明确标注 `# 补充条款（UP-20260715-015 / W11-B）` |
| 第 6 节变更记录追加 | ✅ | 2026-07-15 行已追加，标注 `决策 2 补充条款（UP-20260715-015）` |

---

## 5. 集成测试结果

### 5.1 新建 `tests/integration/test_farewell_5_lines.py`

7 个测试方法：

| # | 测试方法 | 验证内容 |
|---|---|---|
| 1 | `test_farewell_2011_has_5_lines` | farewell_2011 的 5 句备选 + selection_rule + UP-20260715-015 brief 对齐 |
| 2 | `test_photo_lab_2008_has_5_lines` | photo_lab_2008 的 5 句备选 + selection_rule + 5 个 2008 行为种子对齐 |
| 3 | `test_reunion_2024_has_5_lines` | reunion_2024 的 5 句备选（已 W4 跑通，验证对齐）+ 跨年代覆盖（3×2008 + 2×2011）|
| 4 | `test_three_scenes_5_lines_design_pattern_unified` | 3 scene 设计模式统一性硬约束（required 字段集相同 + optional 字段在白名单内）|
| 5 | `test_schema_and_decision_2_supplementary` | schema 加 candidate_lines + 决策 2 补充条款 + 审批变更记录 |
| 6 | `test_selection_rule_fallback_returns_line_01` | selection_rule 兜底冒烟（empty triggered → line_01；多触发 → 最高优先级）|
| 7 | `test_six_decisions_intact` | 红线：6 个决策不能改 + 决策 2 原 5 条 bullets 100% 保留 |

### 5.2 测试运行结果

```
$ python -m pytest tests/integration/test_farewell_5_lines.py -v
============================= test session starts =============================
collected 7 items

tests/integration/test_farewell_5_lines.py::W11BFiveLineUnificationTest::test_farewell_2011_has_5_lines PASSED [ 14%]
tests/integration/test_farewell_5_lines.py::W11BFiveLineUnificationTest::test_photo_lab_2008_has_5_lines PASSED [ 28%]
tests/integration/test_farewell_5_lines.py::W11BFiveLineUnificationTest::test_reunion_2024_has_5_lines PASSED [ 42%]
tests/integration/test_farewell_5_lines.py::W11BFiveLineUnificationTest::test_schema_and_decision_2_supplementary PASSED [ 57%]
tests/integration/test_farewell_5_lines.py::W11BFiveLineUnificationTest::test_selection_rule_fallback_returns_line_01 PASSED [ 71%]
tests/integration/test_farewell_5_lines.py::W11BFiveLineUnificationTest::test_six_decisions_intact PASSED [ 85%]
tests/integration/test_farewell_5_lines.py::W11BFiveLineUnificationTest::test_three_scenes_5_lines_design_pattern_unified PASSED [100%]

============================== 7 passed in 0.53s ==============================
EXITCODE=0
```

**集成测试 7/7 全过**（零回归）。

### 5.3 全量集成测试零回归

```
$ python -m pytest tests/integration/ -v
...
======================= 81 passed, 94 warnings in 9.71s =======================
EXITCODE=0
```

- 原有 `test_end_to_end_three_scenes.py` 8/8 全过（含 W4 的 4 个新测试）
- 原有 74 个其他集成测试 0 回归
- 新增 7 个测试 100% 过

### 5.4 Guard 测试套件零回归

```
$ python -m pytest tests/adversarial/test_four_questions_guard.py -v
...
============================= 85 passed in 0.32s ==============================
EXITCODE=0
```

---

## 6. Guard 验证结果

```
$ python tools/four-questions-guard.py \
  content/case_01_revolution_street/scenes/photo_lab_2008.yaml \
  content/case_01_revolution_street/scenes/farewell_2011.yaml \
  content/case_01_revolution_street/scenes/reunion_2024.yaml \
  --quiet
{
  ...
  "summary": {
    "total_documents": 3,
    "passing_documents": 3,
    "blocking_documents": 0
  }
}
EXITCODE=0
```

**3/3 全过，0 blocking**。

**3 scene 的 D_mandatory_echo_declared 详情**：
- `photo_lab_2008.yaml`: 3 mandatory echo(es) declared
  - photo_in_pocket
  - photo_in_book
  - **admit_2008_behaviors_5_candidate_lines** ← W11-B 新增
- `farewell_2011.yaml`: 3 mandatory echo(es) declared
  - grip_then_release_2011
  - bus_ticket_pair_unused
  - **admit_1985_behaviors_5_candidate_lines** ← W11-B 新增
- `reunion_2024.yaml`: 5 mandatory echo(es) declared
  - two_photos_takeout_compare
  - first_words_admit_2008_2011
  - grip_release_2024_echo
  - bus_ticket_2024_seen
  - i_arrived_text_2024_resonance

Q1/Q2 在 scene_contract 上是 advisory（决策 6 blocking 政策：scene_contract 只 D 是硬阻断）。blocking_documents: 0 → guard 5/5 全过。

---

## 7. 红线对账

| 红线 | 状态 | 证据 |
|---|---|---|
| ❌ 不要让 farewell_2011 5 句备选与 reunion_2024 设计模式不同 | ✅ | 3 scene 同一设计模式：5 lines + same required 字段集 + selection_rule + line_01 fallback；test_three_scenes_5_lines_design_pattern_unified 验证 |
| ❌ 不要让 AI 自由发挥 5 句台词的选择 | ✅ | 3 scene 的 selection_rule.red_line 都含「AI 导演不得在 candidate_lines 之外创造台词」+ 禁止标记（不得/禁止）；test_selection_rule_fallback_returns_line_01 验证兜底 |
| ❌ 不要让 mandatory echo 缺失 | ✅ | 3 scene 的 D_mandatory_echo_declared 全部 passed（photo_lab 3 / farewell 3 / reunion 5）|
| ❌ 不要修改 6 个决策 | ✅ | 决策 1/3/4/5/6 完全没动；决策 2 原 5 条 bullets 100% 保留；test_six_decisions_intact 验证 |
| ❌ 不要修改 schema 之外的字段 | ✅ | narrative_contract.schema.json 只**新增** mandatory_echoes + candidate_lines + selection_rule 字段；其他字段不动 |
| 6 个决策的硬约束段 | ✅ | 「AI 原生门槛 / 付费解锁 / mandatory echo / BYOK / 硬红线 / CI 阻断」全部 100% 保留 |
| 决策 2 补充条款不算改决策 | ✅ | 明确标注 `# 补充条款（UP-20260715-015 / W11-B）`；第 6 节变更记录追加；决策 2 标题与原 5 条 bullets 未动 |
| _legacy_v6/ 不能动 | ✅ | 整个任务只触碰 `content/case_01_revolution_street/scenes/{photo_lab_2008,farewell_2011,reunion_2024}.yaml` + `server/config/schemas/narrative_contract.schema.json` + `docs/design/requirements-review-v1.md` + `tests/integration/test_farewell_5_lines.py` + 本 report |
| YAML 1.2 / UTF-8 | ✅ | `yaml.safe_load` 通过；中文 5 句备选 + 补充条款 100% 完整；BOM 验证通过 |
| 严格遵守 narrative_contract.schema.json | ✅ | 3 scene 的 5 句备选 + selection_rule 都通过 schema 验证（additionalProperties: false 通过）|

---

## 8. 文件路径

### 8.1 修改的文件

| 文件 | 改动 |
|---|---|
| `D:/G1-ai-native/content/case_01_revolution_street/scenes/farewell_2011.yaml` | 新增 `mandatory_echoes[2] = admit_1985_behaviors_5_candidate_lines`（5 句备选 + selection_rule）；causal_seeds 新增 5 个 1985/1986/1989 种子 |
| `D:/G1-ai-native/content/case_01_revolution_street/scenes/photo_lab_2008.yaml` | 新增 `mandatory_echoes[2] = admit_2008_behaviors_5_candidate_lines`（5 句备选 + selection_rule）|
| `D:/G1-ai-native/content/case_01_revolution_street/scenes/reunion_2024.yaml` | `first_words_admit_2008_2011.candidate_lines` 每行加 `seed_id` 字段（与 `referenced_seed` 等价）|
| `D:/G1-ai-native/server/config/schemas/narrative_contract.schema.json` | 新增 `mandatory_echoes` + `candidate_lines` + `selection_rule` 字段定义 |
| `D:/G1-ai-native/docs/design/requirements-review-v1.md` | 决策 2 追加补充条款 + 第 6 节变更记录追加 |

### 8.2 新建的文件

| 文件 | 改动 |
|---|---|
| `D:/G1-ai-native/tests/integration/test_farewell_5_lines.py` | 7 个测试方法（3 scene 5 句备选 + 设计模式统一 + schema + 决策 2 补充条款 + 兜底冒烟 + 6 决策完整）|
| `D:/G1-ai-native/docs/design/w11-b-farewell-5lines-report.md` | 本报告 |

### 8.3 未触碰的文件

- `D:/G1-ai-native/_legacy_v6/`（红线）
- `D:/G1-ai-native/docs/design/w4-content-update-report.md`（W4 报告，不需更新）
- `D:/G1-ai-native/tests/integration/test_end_to_end_three_scenes.py`（W4 测试，零回归）
- 决策 1/3/4/5/6 任何段落
- 6 个决策的硬约束段

---

## 9. 3 scene 5 句台词一览（最终交付）

### 9.1 photo_lab_2008 — `admit_2008_behaviors_5_candidate_lines`

| priority | line_id | speaker | 台词 | seed_id |
|---:|---|---|---|---|
| 1 | line_01_photo_in_pocket | leila | "我把这一张放进包里……你不会怪我吧？" | photo_in_pocket |
| 2 | line_02_photo_in_book | arash | "这一张我夹进诗集……你替我留着诗吗？" | photo_in_book |
| 3 | line_03_grip_then_release | leila | "我们刚才握了一下手……又松开了" | grip_then_release |
| 4 | line_04_poem_in_toolbox | arash | "你那张折诗我收进工具盒了……别告诉任何人" | poem_in_toolbox |
| 5 | line_05_date_written_on_back | leila | "我在照片背面写了 2008.6.21……你看不看得到" | date_written_on_back |

### 9.2 farewell_2011 — `admit_1985_behaviors_5_candidate_lines`

| priority | line_id | speaker | 台词 | seed_id |
|---:|---|---|---|---|
| 1 | line_01_walkman_in_pocket_1985 | arash | "那个 walkman 我一直留着……" | walkman_in_pocket_1985 |
| 2 | line_02_postcard_moscow_vienna | arash | "你 1986 年那张明信片……我从维也纳带过来了" | postcard_moscow_vienna |
| 3 | line_03_grip_then_release_1985 | leila | "你握住又松开……和我们第一次听你弹琴那晚一模一样" | grip_then_release_1985 |
| 4 | line_04_chocolate_wrapper_1986 | leila | "你那两颗松子糖锡纸……我口袋里一直留到现在" | chocolate_wrapper_1986 |
| 5 | line_05_arrival_postcard_1989 | arash | "1989 年那条'我到了'的明信片……我一直贴在琴盖上" | arrival_postcard_1989 |

### 9.3 reunion_2024 — `first_words_admit_2008_2011`

| priority | line_id | speaker | 台词 | seed_id |
|---:|---|---|---|---|
| 1 | line_01_photo_in_pocket | arash | "你把那张照片带在身上带了多少年？" | photo_in_pocket |
| 2 | line_02_photo_in_book | arash | "我在诗集里一直留着那张照片……" | photo_in_book |
| 3 | line_03_grip_then_release | arash | "你握住又松开……和那时候一模一样。" | grip_then_release |
| 4 | line_04_bus_ticket_pair | leila | "你那两张 304 公交票……阿拉什你一直留着吗？" | bus_ticket_pair_unused |
| 5 | line_05_i_arrived_text | leila | "2011 年那条'我到了'的短信……我一直存着。" | i_arrived_text |

### 9.4 统一 selection_rule（3 scene 同一形态）

```yaml
selection_rule:
  algorithm: |
    1. NPC Agent 拉取玩家本局触发的所有 causal_seed 列表
       （from player_action.evidenceIds + npc_raised_echoes + belief_matrix.memoryRefs）
    2. 对 candidate_lines 按 priority 升序遍历，找到第一个
       seed_id / referenced_seed 在玩家触发列表里的 line
    3. 若多触发：取 priority 最小（即"最触动"）的那条
    4. 若无任何 candidate 匹配：AI 导演必须使用 line_01 兜底
       —— 禁止自由发挥台词
  red_line: "AI 导演不得在 candidate_lines 之外创造台词"
```

---

## 10. 验证命令

```bash
# 1. Guard（3/3 全过，EXITCODE=0）
cd D:/G1-ai-native
python tools/four-questions-guard.py \
  content/case_01_revolution_street/scenes/photo_lab_2008.yaml \
  content/case_01_revolution_street/scenes/farewell_2011.yaml \
  content/case_01_revolution_street/scenes/reunion_2024.yaml \
  --quiet
# Expect: "passing_documents": 3, "blocking_documents": 0, EXITCODE=0

# 2. W11-B 集成测试（7/7 全过）
cd D:/G1-ai-native
python -m pytest tests/integration/test_farewell_5_lines.py -v
# Expect: "7 passed in 0.53s", EXITCODE=0

# 3. 全量集成测试（81/81 全过，零回归）
cd D:/G1-ai-native
python -m pytest tests/integration/ -v
# Expect: "81 passed, 94 warnings in 9.71s", EXITCODE=0

# 4. Guard 测试套件（85/85 全过，零回归）
cd D:/G1-ai-native
python -m pytest tests/adversarial/test_four_questions_guard.py -v
# Expect: "85 passed in 0.32s", EXITCODE=0
```

---

## 11. 后续建议（不在本任务范围）

1. **resolver 端**：`candidate_lines` + `selection_rule` 的运行时选择逻辑需要在 W3-B NPC Agent 中实现（用 `referencedMemoryIds` 自动匹配 causal_seed，按 priority 取最触动）。当前测试只验证 contract 层面的 5 行存在 + 红线。
2. **schema 配套**：`client/src/types/schemas.ts` 的 `NarrativeContract` 也需要同步加 `mandatory_echoes` + `candidate_lines` 字段（W4 已经为 `narratorVoice` enum 做过一次同步，本次需要再做一次）。
3. **resolver Agent 实现**：当前 `_assert_candidate_lines_unified` 中的 selection_rule 兜底算法是**测试**层面的 4 行实现，production resolver 需要完整实现。
4. **1985 行为种子补充**：farewell_2011.yaml 的 causal_seeds 新增的 5 个 1985/1986/1989 种子，目前只是声明了存在；这些种子的实际触发与跨年代 carry 还需要在更早的场景（如果存在）或前置内容中定义。
5. **ADR 联动**：建议在 ADR 0007（case-scoped 短码）的下一次更新中把 W11-B 的 5 句备选 + selection_rule 模式作为 case_01 的复用基线（3 scene 5 句备选统一设计模式）写进去。
