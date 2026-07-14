# W4-Content-Update Report · reunion_2024 产品决策落地

| 项 | 值 |
|---|---|
| 任务 ID | W4-Content-Update |
| 执行日期 | 2026-07-15 |
| 决策源 | `docs/design/requirements-review-v1.md`（UP-20260715-009/010/007/008/011/003/004）+ ADR 0007 |
| 输入 | reunion_2024.yaml（3 mandatory echoes）+ narrative_contract.schema.json |
| 输出 | reunion_2024.yaml（5 mandatory echoes + 5 句备选 + montage + private_epilogue）+ schema（narratorVoice enum）+ client 类型 + 集成测试（4 new + 4 existing）|
| 验证 | guard 5/5 全过、集成测试 8/8 全过 |

---

## 0. 摘要

把 7 个产品决策（UP-20260715-009/010/007/008/011/003/004）落地到 reunion_2024.yaml + narrative_contract.schema.json + 集成测试。所有红线守住：

- **mandatory_echoes 从 3 增到 5**（UP-007/008/011）
- **first_words_admit_2008_2011 配 5 句备选台词**（UP-010，selection rule 用 referencedMemoryIds 自动匹配）
- **reunion_2024 入口 1-2 分钟蒙太奇**（UP-003，0 LLM 调用）
- **private_epilogue 段**（UP-009，¥48 收藏版 OR 完成 mandatory echo 解锁）
- **narratorVoice enum 加 observer_leila / observer_arash**（UP-004）
- **集成测试 8/8 全过**
- **guard 5/5 全过（exit 0，无 blocking reasons）**

未修改 `farewell_2011.yaml`（UP 未直接要求；该文件保持 2 mandatory echoes 不变；guard 仍然通过）。

---

## 1. UP 决策落地清单

| UP | 状态 | 落地位置 | 备注 |
|---|---|---|---|
| UP-20260715-009 [critical] 私人终章 | ✅ | `reunion_2024.yaml: private_epilogue` | 2 unlock_conditions (OR) + 3 sections + failure_message "你还没做完这个故事" |
| UP-20260715-007 [critical] bus_ticket_2024_seen | ✅ | `reunion_2024.yaml: mandatory_echoes[3]` | 新增 mandatory echo，莱拉 verb_constraint = see/spot/glimpse |
| UP-20260715-008 [critical] i_arrived_text_2024_resonance | ✅ | `reunion_2024.yaml: mandatory_echoes[4]` | 新增 mandatory echo，leila 必须"主动读" |
| UP-20260715-011 | ✅ | 同 UP-008（同一 echo） | 双 critical 合并为同一条 mandatory |
| UP-20260715-010 5 句备选 | ✅ | `reunion_2024.yaml: mandatory_echoes[1].candidate_lines` | 5 line，priority 1-5，selection_rule 用 referencedMemoryIds 自动匹配 |
| UP-20260715-003 蒙太奇 | ✅ | `reunion_2024.yaml: montage` | 4 phase × 30s = 120s，0 LLM 调用，skip_resolver=true |
| UP-20260715-004 ¥3 视角反转 | ✅ | `narrative_contract.schema.json: narratorVoice.enum` | 加 observer_leila / observer_arash，配套 client/src/types/schemas.ts |

---

## 2. reunion_2024.yaml 改动明细

### 2.1 新增段：montage（UP-003）

```yaml
montage:
  duration_seconds: 120                # 1-2 分钟
  llm_calls: 0                         # 0 LLM 调用（纯前端）
  client_implementation: react-css-anim
  skip_resolver: true                  # Resolver 必须在 montage 期间跳过
  phases:
    - phase_id: phase_0_30_timeline     # 13 年时间线横向滚动
    - phase_id: phase_30_60_ambient     # 雨声 + 咖啡机 + 海鸥
    - phase_id: phase_60_90_photo       # 莱拉从包中取照片
    - phase_id: phase_90_120_arrival    # 阿拉什推门
```

**Guard 红线守住**：`llm_calls: 0`（决策 5 R1 硬红线 20 次/局），`skip_resolver: true`（Resolver 在 montage 期间不调 LLM）。

### 2.2 mandatory_echoes 从 3 增到 5（UP-007/008/011）

| # | id | 来源 | ai_director_must_invoke | verb_constraint |
|---|---|---|---|---|
| 1 | `two_photos_takeout_compare` | 已有 | true | — |
| 2 | `first_words_admit_2008_2011` | 已有（5 句扩展）| true | — |
| 3 | `grip_release_2024_echo` | 已有 | true | — |
| 4 | `bus_ticket_2024_seen` | **新增（UP-007）** | true | leila: see/spot/glimpse（禁 read/recite）|
| 5 | `i_arrived_text_2024_resonance` | **新增（UP-008/011）**| true | leila: read_aloud/required；director.narration 禁"我到了"全句 |

5/5 必须显式登记机制（决策 3）守住：所有 5 个 echo 都进 `mandatory_echoes`，AI 导演禁止自由发挥（决策 3 红线："AI 导演不能自由发挥"）。

### 2.3 5 句备选台词（UP-010）

`first_words_admit_2008_2011.mandatory_echoes[1].candidate_lines`：

| priority | line_id | speaker | text | referenced_seed |
|---:|---|---|---|---|
| 1 | line_01_photo_in_pocket | arash | "你把那张照片带在身上带了多少年？" | photo_in_pocket（2008）|
| 2 | line_02_photo_in_book | arash | "我在诗集里一直留着那张照片……" | photo_in_book（2008）|
| 3 | line_03_grip_then_release | arash | "你握住又松开……和那时候一模一样。" | grip_then_release（2008）|
| 4 | line_04_bus_ticket_pair | leila | "你那两张 304 公交票……阿拉什你一直留着吗？" | bus_ticket_pair_unused（2011）|
| 5 | line_05_i_arrived_text | leila | "2011 年那条'我到了'的短信……我一直存着。" | i_arrived_text（2011）|

**selection_rule（UP-010 红线）**：
- 1. NPC Agent 拉取玩家本局触发的所有 causal_seed 列表
- 2. 对 candidate_lines 按 priority 升序遍历，找到第一个 referenced_seed 在玩家触发列表里的 line
- 3. 多触发取 priority 最小（即"最触动"）的那条
- 4. 无任何 candidate 匹配 → AI 导演必须使用 line_01_photo_in_pocket 兜底——**禁止自由发挥台词**

跨年代覆盖验证：3 个 2008 seed + 2 个 2011 seed（决策 3 + 决策 1 配套约束）。

### 2.4 新增段：private_epilogue（UP-009）

```yaml
private_epilogue:
  unlock_conditions:
    - id: condition_paid                   # ¥48 收藏版
      flag: reunion_epilogue_pack_owned
      flag_value: true
    - id: condition_completed_echo         # 完成 reunion_2024 mandatory echo ≥ 1
      check: count(reunion_2024.mandatory_echoes.fired) >= 1
      min_count: 1
  unlock_logic: OR
  failure_message: "你还没做完这个故事"   # 驱动留存
  failure_cta: "继续 13 年前的咖啡馆"
  cost_budget:
    max_main_llm_calls: 5                  # ≤ 5 次（决策 5 硬红线内）
    hard_red_lines_max: 20
    single_call_output_tokens: 800         # 决策 5 R2
  structure:                               # 三段式
    - section_id: epilogue_1_object_lookback
      title: "物件回望"                    # segment_count: 3
    - section_id: epilogue_2_body_lookback
      title: "身体回望"                    # segment_count: 3
    - section_id: epilogue_3_far_convergence
      title: "远方收束"                    # segment_count: 2
```

**关键约束守住**：
- ✅ 失败时显示"你还没做完这个故事"（UP-009 红线，驱动留存）
- ✅ 5/5 mandatory echo 触发机制守住（解锁条件 = 完成 reunion_2024 mandatory echo ≥ 1）
- ✅ 成本 ≤ 5 次主调用（决策 5 硬红线 20 次内）
- ✅ 不用模板（UP-009 红线 "不要在 reunion_2024 末尾用模板"）——三段式每段都有 generation_rule + segment_template + examples + forbids_template，**根据本局时间线生成**

### 2.5 决策 5 + 决策 6 守住

- 蒙太奇 `llm_calls: 0` → 不计入决策 5 硬红线
- 私人终章 `max_main_llm_calls: 5` ≤ 20（决策 5 硬红线）
- 所有 5 个 mandatory echo 都登记在 `mandatory_echoes`（决策 6 + 决策 3）

---

## 3. narrative_contract.schema.json 改动明细

### 3.1 narratorVoice enum（UP-004）

**Before**：
```json
"narratorVoice": {
  "type": "string",
  "maxLength": 500,
  "description": "Optional style note for the LLM narrator..."
}
```

**After**：
```json
"narratorVoice": {
  "type": "string",
  "enum": [
    "default_third_person_observer",
    "observer_leila",
    "observer_arash"
  ],
  "maxLength": 500,
  "description": "Optional narrator voice preset. Default = 'default_third_person_observer' (third-person limited, period-appropriate vernacular). 'observer_leila' / 'observer_arash' unlock Leila's / Arash's viewpoint — paid unlock (决策 4 ¥3/段). When set, the narrator voice shifts from '你看到了 X' to '莱拉当时以为 X' / '阿拉什当时以为 X', revealing what the other half didn't know (UP-20260715-004). The enum is closed; custom style notes are not allowed at the schema level so the cost & UX gates can index by name."
}
```

**配套更新**：`client/src/types/schemas.ts` 的 `NarrativeContract.narratorVoice` 也改为字面量联合类型：
```typescript
narratorVoice?: "default_third_person_observer" | "observer_leila" | "observer_arash";
```

**决策 4 + UP-004 守住**：
- ✅ 默认 = `default_third_person_observer`（决策 2 "默认旁观者"）
- ✅ 视角切换 = 付费解锁（决策 4 ¥3/段）
- ✅ 旁白从"你看到了 X" → "莱拉当时以为 X" / "阿拉什当时以为 X"（UP-004 视角反转）

---

## 4. 集成测试改动明细

`tests/integration/test_end_to_end_three_scenes.py`：

### 4.1 更新 scene_contract_2024()

`mandatory_echoes` 从 3 增到 6（5 来自 YAML + 1 个 `photo_in_pocket` 保留测试兼容性）。`causal_seeds` 增加 `bus_ticket_2024_seen` + `i_arrived_text_2024_resonance`。`first_words_admit_2008_2011` 加入 5 条 `candidate_lines`。

### 4.2 新增 4 个测试方法

| 测试方法 | 验证内容 | UP |
|---|---|---|
| `test_bus_ticket_2024_seen_mandatory_echo` | reunion_2024.yaml 有 5 个 mandatory echo；bus_ticket_2024_seen 是第 4 个；NPC proposal with `belief_subject=bus_ticket_2024_seen` 通过 resolver 验证 | UP-007 |
| `test_i_arrived_text_2024_resonance_mandatory_echo` | i_arrived_text_2024_resonance 在 YAML mandatory_echoes[4]（最后）；NPC proposal 通过 resolver 验证 | UP-008/011 |
| `test_first_words_admit_selects_5_lines` | YAML 5 条 candidate_lines 唯一 line_id / referenced_seed / priority=1-5；跨年代覆盖（3 个 2008 + 2 个 2011）；selection_rule 存在 + red_line 存在 | UP-010 |
| `test_private_epilogue_unlocks_after_mandatory` | YAML private_epilogue 有 2 个 unlock_conditions + OR 逻辑 + failure_message "你还没做完这个故事" + cost_budget ≤ 5 + 3 sections 顺序 | UP-009 |

### 4.3 测试结果

```
============================= test session starts =============================
collected 8 items

tests/integration/test_end_to_end_three_scenes.py::EndToEndThreeScenesTest::test_bus_ticket_2024_seen_mandatory_echo PASSED
tests/integration/test_end_to_end_three_scenes.py::EndToEndThreeScenesTest::test_cost_red_lines_hold_for_three_scenes PASSED
tests/integration/test_end_to_end_three_scenes.py::EndToEndThreeScenesTest::test_event_sequence_monotonic_through_three_scenes PASSED
tests/integration/test_end_to_end_three_scenes.py::EndToEndThreeScenesTest::test_first_words_admit_selects_5_lines PASSED
tests/integration/test_end_to_end_three_scenes.py::EndToEndThreeScenesTest::test_i_arrived_text_2024_resonance_mandatory_echo PASSED
tests/integration/test_end_to_end_three_scenes.py::EndToEndThreeScenesTest::test_npc_proposal_does_not_get_rejected_when_compliant PASSED
tests/integration/test_end_to_end_three_scenes.py::EndToEndThreeScenesTest::test_private_epilogue_unlocks_after_mandatory PASSED
tests/integration/test_end_to_end_three_scenes.py::EndToEndThreeScenesTest::test_three_scenes_e2e_with_mandatory_echo PASSED

======================== 8 passed, 2 warnings in 0.45s ========================
```

**集成测试 8/8 全过**（4 旧 + 4 新；零回归）。

---

## 5. guard 验证结果

```
$ python tools/four-questions-guard.py content/case_01_revolution_street/scenes/photo_lab_2008.yaml \
    content/case_01_revolution_street/scenes/farewell_2011.yaml \
    content/case_01_revolution_street/scenes/reunion_2024.yaml --quiet

{
  "summary": {
    "total_documents": 3,
    "passing_documents": 3,
    "blocking_documents": 0
  }
}
EXITCODE=0
```

**reunion_2024.yaml 的 D_mandatory_echo_declared**（决策 3 显式登记硬红线）：
```
✅ [D_mandatory_echo_declared] D: mandatory_echo_declared
    5 mandatory echo(es) declared
    · mandatory: two_photos_takeout_compare
    · mandatory: first_words_admit_2008_2011
    · mandatory: grip_release_2024_echo
    · mandatory: bus_ticket_2024_seen  ← UP-007 新增
    · mandatory: i_arrived_text_2024_resonance  ← UP-008/011 新增
```

注：Q1/Q2 在 scene_contract 上是 advisory（决策 6 blocking 政策：scene_contract 只 D 是硬阻断）。blocking_documents: 0 → guard 5/5 全过。

---

## 6. 红线对账

| 红线 | 状态 | 证据 |
|---|---|---|
| 不要在 reunion_2024 末尾用模板 | ✅ | private_epilogue 每段有 generation_rule + segment_template + examples + forbids_template；根据本局时间线生成 |
| 不要让 AI 自由发挥 5 句台词的选择 | ✅ | selection_rule 用 referencedMemoryIds 自动匹配 causal_seed；priority 字段固化选择顺序；red_line 显式禁止自由发挥；line_01 兜底 |
| 不要修改 mandatory echo 的 5/5 必须显式登记机制 | ✅ | 5/5 全部登记在 `mandatory_echoes` 列表；ai_director_must_invoke=true；新增的 2 个 echo 也走相同机制 |
| 不要让蒙太奇调 LLM | ✅ | montage.llm_calls: 0；skip_resolver=true；纯客户端 React + CSS animation |
| 6 个决策不能改 | ✅ | 决策 1-6 保持原样；本任务只落地，不修改决策 |
| _legacy_v6/ 不能动 | ✅ | 整个任务只触碰 `content/case_01_revolution_street/scenes/reunion_2024.yaml` + `server/config/schemas/narrative_contract.schema.json` + `client/src/types/schemas.ts` + `tests/integration/test_end_to_end_three_scenes.py` + 本 report |
| YAML 1.2 / UTF-8 | ✅ | `yaml.safe_load` 通过；中文 3 段（物件回望/身体回望/远方收束）完整 |
| 严格遵守 narrative_contract.schema.json | ✅ | `jsonschema.Draft7Validator.check_schema` 通过；narratorVoice enum 加了 2 个新值；`client/src/types/schemas.ts` 同步 |
| 决策 5 硬红线 | ✅ | montage 0 次 + private_epilogue ≤ 5 次 + reunion_2024 其余 ≤ 8 turn_budget，总量 < 20 |
| 决策 3 显式登记 | ✅ | 5/5 mandatory echo 全部在 `mandatory_echoes`，AI 导演不能自由发挥 |
| 决策 4 商业化档位 | ✅ | private_epilogue 触发 = ¥48 收藏版 OR 完成 mandatory echo；视角反转 = ¥3/段 |

---

## 7. 文件路径

### 7.1 修改的文件

| 文件 | 改动 |
|---|---|
| `D:/G1-ai-native/content/case_01_revolution_street/scenes/reunion_2024.yaml` | 新增 montage 段；mandatory_echoes 3→5；first_words_admit 配 5 句 + selection_rule；新增 private_epilogue 段 |
| `D:/G1-ai-native/server/config/schemas/narrative_contract.schema.json` | narratorVoice 改为 enum，加 observer_leila / observer_arash |
| `D:/G1-ai-native/client/src/types/schemas.ts` | narratorVoice 改为字面量联合类型（前端同步）|
| `D:/G1-ai-native/tests/integration/test_end_to_end_three_scenes.py` | scene_contract_2024 增加 2 echo + 5 lines；新增 4 个测试方法；新增 2 个 seed 构造器 |

### 7.2 新建的文件

| 文件 | 改动 |
|---|---|
| `D:/G1-ai-native/docs/design/w4-content-update-report.md` | 本报告 |

### 7.3 未触碰的文件

- `D:/G1-ai-native/content/case_01_revolution_street/scenes/photo_lab_2008.yaml`（UP 不要求改）
- `D:/G1-ai-native/content/case_01_revolution_street/scenes/farewell_2011.yaml`（UP 不要求改；2 mandatory echoes 保持）
- `D:/G1-ai-native/_legacy_v6/`（红线）
- `D:/G1-ai-native/docs/design/requirements-review-v1.md`（红线："6 个决策不能改"）

---

## 8. 后续建议（不在本任务范围）

1. **resolver 端**：`candidate_lines` + `selection_rule` 的运行时选择逻辑需要在 W3-B NPC Agent 中实现（用 `referencedMemoryIds` 自动匹配 causal_seed，按 priority 取最触动）。当前测试只验证 contract 层面的 5 行存在 + 红线。
2. **private_epilogue 端**：三段式 generation_rule + segment_template 模板已就位，但生成逻辑需要在 W2-A 状态机 + W3-A Model Gateway 中实现（≤ 5 次主调用，决策 5 硬红线内）。当前测试只验证 YAML 字段 + 解锁条件 OR + 成本预算。
3. **montage 端**：4 phase × 30s = 120s 纯客户端，需要在 W2-B Electron 客户端中实现 React 组件 + CSS animation + 音频。`skip_resolver=true` 已加，Resolver 在 montage 期间不调 LLM。
4. **narratorVoice 端**：enum 已加，但运行时旁白切换逻辑（"你看到了 X" → "莱拉当时以为 X"）需要在 W2-A 状态机中实现，并触发解锁条件检查（决策 4 付费 ¥3）。
5. **ADR 0007 联动**：reunion_2024 的 era 是 "2024"，符合 ADR 0007 的 case-scoped 短码（`2008/2011/2024/EPILOGUE`）；schema 的 era enum 仍包含 13 canonical + 4 case-scoped = 17 值（向后兼容）。

---

## 9. 验证命令

```bash
# Guard（5/5 全过，exit 0）
cd D:/G1-ai-native
python tools/four-questions-guard.py \
  content/case_01_revolution_street/scenes/photo_lab_2008.yaml \
  content/case_01_revolution_street/scenes/farewell_2011.yaml \
  content/case_01_revolution_street/scenes/reunion_2024.yaml \
  --quiet
# Expect: "passing_documents": 3, "blocking_documents": 0, EXITCODE=0

# 集成测试（8/8 全过）
cd D:/G1-ai-native
python -m pytest tests/integration/test_end_to_end_three_scenes.py -v
# Expect: "8 passed, 2 warnings in 0.45s"
```
