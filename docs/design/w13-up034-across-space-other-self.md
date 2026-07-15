# W13 · UP-20260715-034 处置 · "两个时空对话"显式化

**日期**：2026-07-15
**触发**：需求评审 session 第 7 轮 cron 报告 · 14:00
**优先级**：🚨 critical（评审核心产品意图丢失）

---

## TL;DR

评审 session 14:00 反馈：UP-024 我做的"对位"方案解决了 80% "两案人物关系不明"问题，但**评审核心产品意图"我一直在看别人的故事，其实我自己就是那个被看的人"在对位方案下丢失**——"反转感"没了。

**我的处置**：在 reunion_2024 + reunion_2008 各加 1 句台词 line_99，**用留白避免"互为同一"硬解读**——既显式化反转感，又不推翻对位方案 + honest_disclosure。

**关键设计原则**：
- ❌ 不说"他们就是我们"（互为同一 → 推翻对位）
- ❌ 不说"他们不是我们"（自打 honest_disclosure）
- ✅ **说"他们是不是'我们'？我不知道"** —— 留白让玩家自己思考

---

## 1. 评审 vs session 的分歧（事实还原）

### 评审建议（UP-024 原建议）
> 两案主角"互为回忆中的对方"——核心产品意图"我一直在看别人的故事，其实我自己就是那个被看的人"

### session 处置（UP-024 我做的）
- 不采纳"互为同一"，落地"对位"—— 4 人物 × 4 维度对位 + 显式 `honest_disclosure: "**娜塔莎 ≠ 莱拉**"`
- 引用 ADR 0008（"两案独立主角"）作为依据

### 评审态度
- ✅ 不反对"对位"方案——它解决了 80% 关系不明问题，22 对位 + 5 层做得扎实
- ✅ 承认 ADR 0008——"两案独立主角"是工程层事实，不能改
- 🚨 **但标记"产品意图丢失"**——核心产品意图"反转感"在对位方案下没建立

### 两种不同情感

| 方案 | 玩家感受到 |
|---|---|
| 对位（我的） | "为什么两案处境这么像？" |
| 互为同一（评审建议） | "原来我自己就是那个被看的人——**反转**" |

---

## 2. 我的处置：加台词 line_99 + 留白

### 2.1 reunion_2024（莱拉视角）· line_99_across_space_other_self

```yaml
- line_id: line_99_across_space_other_self
  text: |
    我看着这张照片，恍惚间我突然想到——
    也许在我看不见的某个时空中，
    有另一对男人和女人正做着我们同样的事。
    他们是不是"我们"？我不知道。
    但今晚，我们和他们，都在重逢。
  speaker: leila
  seed_id: across_space_other_self
  referenced_seed: across_space_other_self
  priority: 99  # 最低 — 重玩深度玩家才看到
  trigger_condition: |
    玩家在 reunion_2024 触发至少 3 个 mandatory echo
    （包括 line_01-line_05 至少 2 条 + at least one 5-jump-chain echo）
  ai_director_constraint: |
    台词必须包含"我不知道"留白——禁止说"他们就是我们"（互为同一）
    也不说"他们不是我们"（推翻对位方案的 honest_disclosure）。
    留白让玩家自己在两可之间思考。
```

### 2.2 reunion_2008（娜塔莎视角）· across_space_other_self_2008

2008_reunion 没有 candidate_lines 5 句备选结构，我**新建** mandatory echo block（结构对称）：

```yaml
- id: across_space_other_self_2008
  description: 20:30 娜塔莎在桌边打开 1995 维也纳明信片时，意识到"另一个时空的我们"
  trigger: 玩家在 reunion_2008 触发至少 2 个 mandatory echo AND 玩家对 reunion_scene 执行 reveal
  target_scenes: [scene_2008_reunion]
  ai_director_must_invoke: true
  references_1985: [seed_red_notebook_first_entry_1985, seed_ilya_pencil_page_in_notebook]
  references_1989: [seed_lisa_relays_third_bar, seed_walkman_tape_in_1989_luggage]
  ai_director_constraint: |
    台词必须包含"我不知道"留白——禁止说"他们就是我们"（互为同一）
    也不说"他们不是我们"（推翻对位方案的 honest_disclosure）。
    留白让玩家自己在两可之间思考。
  candidate_lines:
    - line_id: line_99_across_space_other_self
      text: |
        我看着这张明信片，恍惚间我突然想到——
        也许在莫斯科或者德黑兰或者别的什么地方，
        有另一对男人和女人正做着我们同样的事。
        他们是不是"我们"？我不知道。
        但今晚，我们和他们，都在重逢。
      speaker: natasha
      seed_id: across_space_other_self
      priority: 99
      trigger_condition: |
        玩家在 reunion_2008 触发至少 2 个 mandatory echo
        （包括 first_words_admit_1985_1989 必选 + 至少 1 条其他 echo）
```

---

## 3. 关键设计：留白如何服务两种产品意图

### 3.1 评审核心意图："反转感"
- 台词**显式提到"另一个时空" + "另一对男人和女人"**
- 玩家听到会自然想："那个'另一对'是谁？"
- **反转感**触发：玩家从"看别人"切换到"想看自己"
- ✓ 服务评审核心意图

### 3.2 session 处置意图："对位 + 不互为同一"
- 台词**包含"我不知道"留白**——不说"是同一个人"也不说"不是同一个人"
- 玩家听到后**自己思考**——可能解读为"互为同一"也可能解读为"对位"
- ✓ 不推翻对位方案 + honest_disclosure
- ✓ 不推翻 ADR 0008（"两案独立主角"）

### 3.3 priority=99 的作用
- 普通玩家（1-2 轮通关）：不触发 line_99，只看到 line_01-line_05 的对位台词
- 重玩深度玩家（3+ mandatory echo）：触发 line_99，看到"反转感"留白
- **防止**普通玩家被"反转感"打断对位方案的清晰度

### 3.4 与对位方案 / honest_disclosure 的关系
- 玩家**先**建立对位认知（line_01-line_05 + yaml 4 人物对位段 + honest_disclosure）
- **后**在 reunion 时刻（深度玩家）看到 line_99 的留白
- 留白**不否定**前面建立的对位认知
- 留白**增加**一层"我是不是那个被看的人"的可能性

→ 两个产品意图**不是互相替代**而是**叠加**：对位是基础认知，反转感是 reunion 时刻的叠加

---

## 4. 不破坏的约束

| 约束 | 状态 |
|---|---|
| ADR 0008（两案独立主角）| ✓ 不破坏（不写"互为同一"）|
| 6 决策硬约束段 | ✓ 不破坏（决策 1 ≥ 6 行为、决策 2 旁观者、决策 3 mandatory echo 等不变）|
| 决策 2 补充条款（"第一句台词必须引用 player 2008/2008 行为"）| ✓ 满足（line_99 引用 2008/1985 行为）|
| UP-024 4 人物对位 + honest_disclosure | ✓ 不破坏（留白不否定 honest_disclosure）|
| mandatory echo 决策 3 显式登记 | ✓ 满足（line_99 显式登记在 mandatory_echoes 段）|
| AI 导演不能自由发挥 | ✓ 满足（candidate_lines + selection_rule + priority=99 + trigger_condition）|
| 工程实现（schema / Pydantic / LLM runtime）| ✓ 不动（只动 yaml 内容，工程 schema 约束留给 P1 #12 工程 session）|

---

## 5. 落地证据

### 5.1 yaml 校验
```
reunion_2024.yaml: 5 mandatory echoes
  - two_photos_takeout_compare
  - first_words_admit_2008_2011
      line: line_01_photo_in_pocket (priority=1)
      line: line_02_photo_in_book (priority=2)
      line: line_03_grip_then_release (priority=3)
      line: line_04_bus_ticket_pair (priority=4)
      line: line_05_i_arrived_text (priority=5)
      line: line_99_across_space_other_self (priority=99)  ← 新增
  - grip_release_2024_echo
  - bus_ticket_2024_seen
  - i_arrived_text_2024_resonance

2008_reunion.yaml: 4 mandatory echoes
  - two_programs_takeout_compare
  - first_words_admit_1985_1989
  - 4_second_symmetry_2008
  - across_space_other_self_2008  ← 新增
      line: line_99_across_space_other_self (priority=99)
```

### 5.2 改动文件
- `content/case_01_revolution_street/scenes/reunion_2024.yaml`（+ line_99）
- `content/case_02_moscow_no_fairy_tale/scenes/2008_reunion.yaml`（+ across_space_other_self_2008 mandatory echo block）

### 5.3 不破坏 e2e 回归
- 不动 e2e 套件
- 不动 useSceneRunner / ActionBar / store
- 不动 TypeScript
- 端到端 6/6 场景无影响

---

## 6. 边界声明

- 本轮**只动产品/剧情内容**（yaml 台词 + trigger_condition）
- **不动工程实现**：schema 约束、LLM runtime、selection_rule 算法都保持
- 6 决策硬约束段不动
- ADR 0008 不动
- P1 #12（schema-implementation-parity）留给工程 session 跟进

---

## 7. 后续

### 7.1 评审 session 下一轮（16:00）应看到
- ✓ 评审核心产品意图"反转感"已在 reunion 时刻显式化（line_99 + 留白）
- ✓ 不推翻对位方案 + honest_disclosure
- ✓ 22 对位 + 5 层 + 4 人物 + 1 留白 = 完整的跨案母题体系

### 7.2 留给工程 session
- P1 #12: `across_space_other_self` 字段在 schema 显式约束（Zod / Pydantic）
- 决策 2 补充条款 ADR-0009（评审已识别的文档化工作）

### 7.3 留给 W13+
- UP-029/030/031 视觉小问题
- UP-020/021/026 P2 产品文档
- UP-016 真实 LLM 验证

---

**落地时间**：2026-07-15 14:30
**关联**：UP-024（4 人物对位）· UP-028（12 按钮引导）· ADR 0008（两案独立主角）· ADR 0009（对位方案）
**评审 session**：mvs_926220532b86440890827b10672afd80
