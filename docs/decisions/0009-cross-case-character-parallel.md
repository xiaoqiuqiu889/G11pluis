# ADR-0009 · 跨案主角对位方案 · 决策

> **状态**：✅ 已采纳
> **决策日**：2026-07-15 14:30
> **决策人**：综合开发任务（mvs_164fd83880c741be978c0c7f0a49e8e5）
> **关联**：ADR 0008（跨案主角关系 · 拒绝"互为同一"建议）· UP-024（评审第 6 轮 critical · 连续 2 轮）
> **范围**：产品/剧情决策（不涉及工程实现细节；schema 字段约束属 P1 #12 留给工程 session）

---

## 1. 背景

评审 session 2026-07-15 12:00 第 6 轮 cron 报告提出 **UP-20260715-024 critical**（连续 2 轮）：

> 跨案母题对应表 `cross_case_equivalents.yaml` 有 10 个物件对应 + 语义连续性，**但 4 个第二案人物（natasha / ilya / lisa / sasha）与第一案人物（leila / arash / maryam / kamran）的对应没做** —— 建议两案主角"互为回忆中的对方"

ADR 0008 已拒绝"互为同一"建议（理由：重写 5 锚点 + 4 人物 + 3 scene 是重大剧情变更，会破坏 mandatory echo 机制）。**本 ADR 是 ADR 0008 的落地方案：跨案主角如何"对位"而不"互为同一"。**

---

## 2. 决策：跨案主角"对位（parallel）"而非"互为同一（identical）"

### 2.1 4 人物对位矩阵

| 案 02 | 案 01 | role_archetype | 视觉对应 | 行为对应 | 关键差异 |
|---|---|---|---|---|---|
| **natasha_roschina** | leila | 记忆修复者 | 20/30/40 代女性三段式 | 用具体物件承载过去 | 物件物理性质不同：照片可撕 vs 笔记本可写 |
| **ilya_berman** | arash | 离散者 | 20/30/40 代男性三段式 | 用个人随身物承载过去 | 阿拉什接受破损 vs 伊利亚主动修复 |
| **sasha_kuzmin** | kamran | 见证者 | 弟弟位（比主角小 2-3 岁）| 用位置守候 | 卡姆兰守十字路口 vs 萨沙守中央 C 琴键 |
| **lisa_hoffmann** | maryam | 过渡者 | 30/40 代女性 | 用一个动作完成桥接 | 玛丽亚姆视觉桥接（快门） vs 莉莎声音桥接（拨号）|

### 2.2 4 维度对位（玩家可感知的统一结构）

每个对位都按以下 4 维度描述：

1. **role_archetype**（角色原型）—— 玩家感知"这是同一种处境的另一版本"
2. **visual_correspondence**（视觉对应）—— 让玩家在两个案里"看到同一种人"
3. **behavioral_pattern**（行为模式）—— 玩家理解"对位不是同一"——同处境不同应对
4. **player_distinction**（玩家感知差异）—— **显式标注"她们不是同一个人"**

第 4 维是关键防线，防止玩家误读成"案 01 + 案 02 是同一拨人的不同时空"。

---

## 3. 为什么是"对位"而不是"互为同一"

### 3.1 玩家体验维度

| 维度 | 对位 | 互为同一 |
|---|---|---|
| 跨案母题 | **可规模化**（一个模板的不同实例）| 不可规模化（每个新案都要重写）|
| 玩家认知 | "我看到莱拉类型的人在另一时空" | "我看到莱拉在 1985 莫斯科"（科幻/穿越）|
| 内容边界 | 案 01 + 案 02 是**两个独立故事** | 案 01 + 案 02 是**同一故事的两段** |
| mandatory echo | 跨案 echo 假设"不同案件独立"（决策 6 红线）| 跨案 echo 变成"同案不同时空"——破坏决策 6 机制 |

### 3.2 剧情边界

- 案 01：伊朗德黑兰 2008-2024（莱拉 + 阿拉什 + 玛丽亚姆 + 卡姆兰）
- 案 02：苏联莫斯科 1985-2008（娜塔莎 + 伊利亚 + 莉莎 + 萨沙）

**两个案**：
- 不同国家（伊朗 vs 苏联/俄罗斯/维也纳/柏林）
- 不同时代（2008-2024 vs 1985-2008）
- 不同文化（伊斯兰 vs 东正教 + 犹太）
- 不同母语（波斯语 vs 俄语 + 德语）
- 不同音乐传统（伊朗古典 vs 苏联学院派）

→ 强行"互为同一"会破坏这 5 个维度的真实性，玩家会问"为什么案 01 莱拉突然会俄语？"

### 3.3 工程边界（不属于本 ADR 范围）

- schema-implementation-parity：`cross_case_equivalents.yaml` 有 `player_distinction.honest_disclosure` 字段，但 schema 未显式约束——这是 P1 #12（工程 session 跟进）
- 字段约束在工程层（Zod schema / Pydantic）落实，不在产品/剧情 ADR 范围

---

## 4. 落地证据

### 4.1 yaml 段落（已在 `cross_case_equivalents.yaml` 落盘）

```yaml
characters:
  - id: natasha_roschina
    case_02_role: protagonist
    case_02_label: 娜塔莎·罗希娜（莫斯科音乐学院大提琴手）
    role_archetype: "记忆修复者 · 主承担者（与案 01 莱拉对位）"
    cross_case_equivalent:
      case_01_character: leila
      semantic_link: "两人都承担'记忆修复者'角色——案 01 莱拉在 2008 地下放映室面对 13 年前的两张同版毕业照 / 案 02 娜塔莎在 1985 305 琴房面对 21 年前的肖斯塔科维奇 Op.38"
    visual_correspondence: {...}   # 年龄段 / 主要物件 / 场景签名
    behavioral_pattern: {...}      # 沉默方式 / 应对离别 / 处理过去
    player_distinction:            # ★ 显式标注"娜塔莎 ≠ 莱拉"
      honest_disclosure: "**娜塔莎 ≠ 莱拉**。她们在不同城市、不同时代、不同文化、不同母语。"
      ...
  - id: ilya_berman      ↔ arash
  - id: sasha_kuzmin    ↔ kamran
  - id: lisa_hoffmann   ↔ maryam
```

### 4.2 与人物卡的关系

- `characters/natasha_roschina.yaml` `role_note: 与第一案莱拉对位；记忆修复者的核心承担者`
- `characters/ilya_berman.yaml` `role_note: 与第一案阿拉什对位；男性主角，移民与离散者`
- yaml 的 `characters` 段把这些**显式化、结构化**

### 4.3 校验

```
top-level keys: ['artifacts', 'atmosphere', 'canonical', 'characters', 'audio']
characters: ['natasha_roschina', 'ilya_berman', 'sasha_kuzmin', 'lisa_hoffmann']
artifacts: 10  atmosphere: 3  canonical: 2
```

---

## 5. 未来案（案 03+）的应用模式

当案 03 出现时，按以下步骤建立对位：

1. **识别案 03 主角 4 人物**
2. **每个案 03 人物**选择一个案 01 角色原型（记忆修复者 / 离散者 / 见证者 / 过渡者 / 新的）
3. **写 4 维度对位**（role_archetype / visual / behavioral / player_distinction）
4. **强制 `player_distinction.honest_disclosure`** 显式标注"案 03 角色 ≠ 案 01 角色"
5. **更新 `content/case_0X_*/artifacts/cross_case_equivalents.yaml`**

---

## 6. 回退窗口

- 用户如不同意本决策，可在 W13 启动前推翻并触发 yaml 重写
- 推翻后保留 ADR 0008 拒绝"互为同一"的立场——回退空间是"是否加更多对位维度"或"是否调整 4 人物的具体配对"

---

## 7. 维护说明

- 本 ADR 索引在 `content/case_02_moscow_no_fairy_tale/artifacts/cross_case_equivalents.yaml` 的 `characters` 段
- 案 03+ 在 `content/case_0X_*/artifacts/cross_case_equivalents.yaml` 同结构落盘
- 与 `content/_shared/motifs/cross_case_motifs.md` 互为引用
- 与 ADR 0008（cross-case-protagonist-relationship）互为引用

---

**决策落地时间**：2026-07-15 14:30
**关联报告**：`docs/design/w12-e2e-runsync-up024-up028.md`
**评审 session**：mvs_926220532b86440890827b10672afd80（产品/体验视角）
