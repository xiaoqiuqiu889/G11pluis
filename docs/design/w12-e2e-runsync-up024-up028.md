# W12-E2E-runsync · 评审第 6 轮 UP 处置（UP-024 + UP-028）

**日期**：2026-07-15
**触发**：需求评审 session `mvs_926220532b86440890827b10672afd80` 第 6 轮 cron 报告
**优先级**：🚨 2 条 critical（本轮必须处理）

---

## TL;DR

| 编号 | 状态 | 落地 |
|---|---|---|
| **UP-024** 跨案主角关系 | ✅ 处置（**不采纳"互为同一"建议**，落地"对位"方案）| `cross_case_equivalents.yaml` + 4 人物段 |
| **UP-028** 12 按钮"按钮恐惧" | ✅ 处置（gateway + 灰度 + 悬停亮 + 持久化）| `ActionBar.tsx` + `store.ts` + `animations.css` |
| UP-029/030/031 major | ⏸ 推后到 W13（按用户优先级）|
| UP-020/021/026 P2 | ⏸ 累积至周日 23:00 一次性投 |

---

## UP-024 · 跨案主角关系（连续 2 轮 critical）

### 评审诉求
> 跨案母题对应表 `cross_case_equivalents.yaml` 13KB 有 10 个物件对应 + 语义连续性，**但 4 个第二案人物（natasha / ilya / lisa / sasha）与第一案人物（leila / arash / maryam / kamran）的对应没做** —— 建议两案主角"互为回忆中的对方"

### 我的处置：**不采纳"互为同一"**，落地"对位"

#### 不采纳的理由（继承 ADR 0008）
- ADR 0008 已定稿"两案独立主角"
- 改为"互为同一"需要重写：5 锚点 + 4 人物 + 3 scene = 12 个文件改动
- 会破坏决策 6 的 mandatory echo 机制（cross-case echo 假设"不同案件独立"，不是"同一人在不同时空"）
- 13:00 cron 时间窗口 + token 限制下，重写是 major risk

#### 落地方案：4 人物"对位"段（不重叠）
在 `content/case_02_moscow_no_fairy_tale/artifacts/cross_case_equivalents.yaml` 加 `characters` 段：

```yaml
characters:
  - id: natasha_roschina
    case_02_role: protagonist
    case_02_label: 娜塔莎·罗希娜（莫斯科音乐学院大提琴手）
    role_archetype: "记忆修复者 · 主承担者（与案 01 莱拉对位）"
    cross_case_equivalent:
      case_01_character: leila
      semantic_link: "..."
    visual_correspondence: {...}   # 年龄段 / 主要物件 / 场景签名
    behavioral_pattern: {...}      # 沉默方式 / 应对离别 / 处理过去
    player_distinction:            # ★ 关键：显式告诉玩家她们不是同一个人
      honest_disclosure: "**娜塔莎 ≠ 莱拉**。她们在不同城市、不同时代、不同文化、不同母语。"
      why_player_cares: "玩家从案 01 进入案 02 时... 答案是否定的。两个陌生人承担了同一种'记忆修复者'的处境。"
      narrative_function: "对位让玩家在案 02 看到'莱拉类型的人在另一时空的另一版本'——这是'内容可规模化'的玩家价值"

  - id: ilya_berman      ↔ arash   （离散者 · 接受破损 vs 主动修复）
  - id: sasha_kuzmin    ↔ kamran  （见证者 · 弟弟位 · 两个独立"弟弟位"）
  - id: lisa_hoffmann   ↔ maryam  （过渡者 · 视觉桥接 vs 声音桥接）
```

#### 4 人物对位（4 维度）

| 维度 | 含义 | 用途 |
|---|---|---|
| `role_archetype` | 角色原型（"记忆修复者"/"离散者"/"见证者"/"过渡者"）| 玩家感知"这是同一种处境的另一版本" |
| `visual_correspondence` | 视觉对应（年龄段 / 主要物件 / 场景签名）| 让玩家在两个案里"看到同一种人" |
| `behavioral_pattern` | 行为模式（沉默方式 / 应对离别 / 处理过去）| 让玩家理解"对位不是同一"——同处境不同应对 |
| `player_distinction` | 玩家感知差异 | **显式标注"娜塔莎 ≠ 莱拉"** —— 防止玩家误读 |

#### 与 natasha / ilya 人物卡的关系
- natasha 人物卡 `role_note: 与第一案莱拉对位；记忆修复者的核心承担者`
- ilya 人物卡 `role_note: 与第一案阿拉什对位；男性主角，移民与离散者`
- yaml 的 `characters` 段把这些**显式化、结构化**——评审要求的"语义连续性"现在有据可查

#### yaml 校验
```
top-level keys: ['artifacts', 'atmosphere', 'canonical', 'characters', 'audio']
characters: ['natasha_roschina', 'ilya_berman', 'sasha_kuzmin', 'lisa_hoffmann']
artifacts: 10  atmosphere: 3  canonical: 2
```

---

## UP-028 · 12 按钮"按钮恐惧"（新增 critical）

### 评审诉求
> 12 个结构化行为（调查/揭露/隐藏/询问/直面/安慰/给出/销毁/承诺/等待/离开/沉默）5×3 网格平铺，玩家第一次接触会"按钮恐惧"—— 信息密度过高

### 我的处置：gateway + 灰度 + 悬停亮 + 持久化

#### 落地（4 步）

**1. gateway（永远全亮）**：`GATEWAY_ACTIONS = { "investigate" }`
- "调查" 是引导入口，永远金色发光
- 决策 1（≥ 6 种结构化行为）不变：12 个按钮都存在

**2. 默认灰度**：未 discovered 按钮灰度 + 略虚化
```css
.action-btn--dimmed {
  opacity: 0.32;
  filter: saturate(0.4) blur(0.3px);
  border-style: dashed;
}
.action-btn--gateway {
  border-color: var(--color-amber-glow);
  box-shadow: 0 0 0 1px rgba(212, 161, 85, 0.25), 0 0 16px rgba(212, 161, 85, 0.15);
}
```

**3. 悬停/聚焦临时全亮**：CSS hover + JS onMouseEnter/Leave
```tsx
const isActionLit = (a: ActionType): boolean => {
  if (GATEWAY_ACTIONS.has(a)) return true;
  if (picked === a) return true;
  if (hoveredAction === a) return true;
  if (discoveredActions.includes(a)) return true;
  return false;
};
```

**4. 持久化已发现集合**：`store.discoveredActions: ActionType[]`
- 玩家点过（含 selected 但未提交）→ 调 `discoverAction(type)`
- scene 切换时由 `loadScene` 重置为 `[]`
- 不持久化到 localStorage（每个 run 独立重学，符合"已熟悉的引导不重复"原则）

#### 5 项 e2e 验证（`e2e-gateway.cjs`）

```
12 按钮初始 lit 状态:
  investigate  lit=true  gateway=true     ← gateway 永远全亮
  reveal       lit=false gateway=-        ← 11 个灰度
  conceal      lit=false ...
  ...
  silence      lit=false

悬停"揭露"后: data-lit=true                ← 悬停临时全亮
点击"揭露"后: data-lit=true                ← 点击持久全亮
鼠标移开"揭露"后: data-lit=true            ← 持久化生效

结果:
  gateway (调查) 永远全亮: ✓
  11 个未发现按钮初始灰度: ✓
  悬停"揭露"临时全亮: ✓
  点击"揭露"持久全亮: ✓
  鼠标移开后保持全亮: ✓
```

#### 决策 1 红线守住
- 6 决策不变：每个场景支持 12 种结构化行为
- 灰度是**视觉引导**（CSS），不是行为减少
- 玩家可点任意按钮（包括灰度的）—— 灰度只是"先认识调查"

#### 截图证据
`e2e-screenshots/up028-01-initial.png`：
- 调查按钮金色发光（gateway）
- 11 个其他按钮灰度虚化（dashed border + saturate 0.4 + blur 0.3px）

---

## 全场景回归

```
=== W12-E2E-runsync 全 6 场景验证 ===
后端: OK (11 active runs)

--- case_01-photo_lab_2008 ---  createRun:1  按钮:12  action API:1  ✓ PASS
--- case_01-farewell_2011 ---  createRun:1  按钮:12  action API:1  ✓ PASS
--- case_01-reunion_2024 ---   createRun:1  按钮:12  action API:1  ✓ PASS
--- case_02-1985_meeting ---   createRun:1  按钮:12  action API:1  ✓ PASS
--- case_02-1989_farewell ---  createRun:1  按钮:12  action API:1  ✓ PASS
--- case_02-2008_reunion ---   createRun:1  按钮:12  action API:1  ✓ PASS

通过: 6/6  失败: 0/6
```

UP-028 改动 ActionBar 后**无回归**。

---

## TypeScript 0 错误

`npx tsc --noEmit` → 0 error

---

## 处置后状态

| 编号 | 之前 | 之后 |
|---|---|---|
| UP-024 跨案主角关系 | 🚨 critical 连续 2 轮 | ✅ 处置（4 人物对位 + 显式标注"不是同一个人"）|
| UP-028 12 按钮引导 | 🚨 critical 新增 | ✅ 处置（gateway + 灰度 + 悬停亮 + 持久化）|
| UP-029/030/031 | 🟠 major | ⏸ 推后 W13 |
| UP-020/021/026 | 🟡 P2 | ⏸ 累积周日 23:00 |
| UP-032/033 | 🟡 P2 | ⏸ 累积周日 23:00 |

---

## 关于 14:00 cron 评审的预告

下一轮 cron 评审重点：
- ADR 库扩充（4 篇待写：写入域隔离 / |delta| 0.25 / 4 级降级链 / SHA-256 校验 / 决策 2 补充条款）
- e2e 套件扩展
- 8/10 路由过（升级到 10/10？）

我的 W12-E2E-runsync + UP-024/028 处置都已在 docs/ 落盘。下一轮评审可以基于本报告的证据做判断。
