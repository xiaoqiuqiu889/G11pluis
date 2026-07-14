# 革命街 AI 原生重构 · 综合开发任务启动 Brief v1

| 项 | 值 |
|---|---|
| From session | mvs_926220532b86440890827b10672afd80（需求评审） |
| To session | mvs_164fd83880c741be978c0c7f0a49e8e5（综合开发任务） |
| 起草时间 | 2026-07-14 |
| 决策源 | `D:/G1-ai-native/docs/design/requirements-review-v1.md`（**唯一权威**） |
| 状态 | 待你点头后启动 W2-W4 |

---

## 1. 上一轮已完成的（不要重做）

- ✅ 读完 v0.1 PRD、《历史模拟器：崇祯》参考报告、《革命街没有尽头》团队复盘
- ✅ 给出《革命街 AI 原生重构 v2》方案
- ✅ W0：`D:/G1-ai-native/` 项目根目录、复制 v6 资产到 `_legacy_v6/`（49 张美术 + 6 个 .ts + 4 个 .md 契约）
- ✅ 启动 5 个 W1 background 子 agent：v6 资产分析 / 双系统对照表 / 事实信念矩阵 / 三场景叙事合同 / JSON Schema 完整版
- ✅ 6 个核心需求决策已定稿（见 `requirements-review-v1.md`）

---

## 2. 第一步：先验收 W1 产物

**不要直接开 W2**。先把 W1 的产物拉清单、看质量、查缺补漏。

### 2.1 预期产物清单

| 任务 | 预期路径 | 预期内容 |
|---|---|---|
| W1-A | `D:/G1-ai-native/analysis/v6_design_inventory.md` | v6 设计资产清单 + AI 原生重构评估（8000-20000 字） |
| W1-B | `D:/G1-ai-native/analysis/dual_system_mapping.md` | v6 ↔ AI 原生双系统对照表（8000+ 字） |
| W1-D | `D:/G1-ai-native/content/case_01_revolution_street/beliefs/facts_beliefs_matrix.md` | 5 锚点 × 4 人物 × 4 层矩阵（6000+ 字） |
| W1-C | `D:/G1-ai-native/content/case_01_revolution_street/scenes/photo_lab_2008.yaml`<br>`farewell_2011.yaml`<br>`reunion_2024.yaml` | 三个场景的完整叙事合同 YAML（每个 200+ 行） |
| W1-E | `D:/G1-ai-native/server/config/schemas/*.json` 8 个文件 | PlayerAction / NPCProposal / DirectorBeat / ResolverOutcome / BeliefMatrix / NarrativeContract / CausalSeed / WorldSnapshot |

### 2.2 验收 checklist

- [ ] 5 个 W1 子 agent 是否都已完成？task_query 拉状态
- [ ] 每个产物是否真实落盘？`Test-Path` 查文件
- [ ] 文件大小是否符合预期？（每个 .md ≥ 6000 字，每个 .yaml ≥ 200 行，每个 .json ≥ 100 行）
- [ ] 4 项自检的"必须废弃"清单是否清晰？
- [ ] JSON Schema 的 enum 钳制是否完整？

### 2.3 缺失补救

如果某些 W1 任务没跑完或产物质量不达标，**补跑缺失的，不要跳过**。

- 缺失 v6 资产分析 → 重新跑 W1-A
- 缺失双系统对照表 → 重新跑 W1-B
- 缺失事实信念矩阵 → 重新跑 W1-D
- 缺失叙事合同 → 重新跑 W1-C（三个场景必须都出）
- 缺失 JSON Schema → 重新跑 W1-E（8 个 schema 必须全有）

---

## 3. 第二步：W2-W4 启动

按 `requirements-review-v1.md` §5 的依赖关系，**串行启动**：

### 3.1 W2 阶段（可三个并行）

| 子 agent | 依赖决策 | 关键产物 |
|---|---|---|
| **W2-A 状态机工程师** | 决策 1（行为门槛）+ 决策 6（自检工具） | `server/engine/` 完整：状态机、Reducer、事件账本、世界快照 |
| **W2-B Electron 客户端工程师** | 决策 2（旁观者 UX）+ 决策 4（付费点 UX） | `client/` 完整：Electron 壳 + React 应用 + 宽银幕 UI |
| **W2-C 内容工具工程师** | 决策 6 | `tools/` 完整：**`four-questions-guard.py` 是 P0**（4 项自检 CLI） |

**并行启动**：3 个 W2 子 agent 之间无依赖关系（除共享决策文档），可以 background 并行。

### 3.2 W3 阶段（可三个并行，依赖 W2 产物）

| 子 agent | 依赖决策 | 关键产物 |
|---|---|---|
| **W3-A Model Gateway 工程师** | 决策 5（成本红线 + 4 级降级） | `server/model/` 完整：OpenAI 兼容、多供应商路由、**4 级降级链** |
| **W3-B AI 导演与角色 Agent 工程师** | 决策 3（mandatory echo）+ 决策 1（行为门槛） | `server/agents/` 完整：Intent Parser + NPC Agent + Director Agent + Resolver |
| **W3-C 校验链与守门工程师** | 决策 5（红线）+ 决策 6（自检工具） | `server/safety/` 完整：Schema 校验 + Clamping + 秘密泄露检测 |

**并行启动**：3 个 W3 子 agent 可以 background 并行。

### 3.3 W4 整合

W4 是单点子 agent（不能用并行子 agent 做整合）：
- 集成所有 W2/W3 产物
- 跑通端到端 demo（30-45 分钟单局可玩）
- 外部体验验证（用户测试 5-10 人）
- 输出最终 demo + 验收报告

---

## 4. 决策红线速查

不要重读完整 6 条决策（`requirements-review-v1.md` §2 是唯一源），但每个 W2-W4 子 agent 在写 prompt 时**必须把对应决策的验收标准带过去**。

最常踩的 5 个坑：

1. **AI 自由聊天**——v0.1 PRD 没明文禁止，但经验教训明文列入"不应沿用"。**所有 NPC 输出走叙事合同 + 提案制，不开自由对话**。
2. **mandatory echo 被 AI 自由发挥**——决策 3 要求 mandatory echo 必须在 `narrative_contract.yaml` 显式登记，**AI 导演不能自由发挥**。
3. **¥1 截句 / 第三方品牌残留 / 客户端权威存档**——决策 4 明文禁止，遇到这种设计冲动直接砍（演示码统一改用 G1N-DEMO-{YEAR}-{NN} 格式，由 `tools/v6_residual_scan.py` 持续扫）。
4. **硬红线被突破**——决策 5 的 4 级降级链必须实现，**不能"为了体验"取消降级**。
5. **4 项自检工具不入 CI**——决策 6 明确要求入 CI，**只做 checklist 不做工具等于没有原则**。

---

## 5. 不要做

- ❌ 重读 v0.1 PRD、《崇祯》参考报告、革命街复盘（评审 session 已读）
- ❌ 重写 6 个决策（已定稿）
- ❌ 动 `_legacy_v6/` 下的任何文件（只读参考）
- ❌ 重新设计目录结构（W0 已搭好）
- ❌ 在旧 v6 客户端 UI 上继续堆 AI 聊天框
- ❌ 把 AI 调用成本省到影响 mandatory echo 触发（mandatory 是 P0 优先级）

---

## 6. 风险与暂停条件

如果遇到以下情况，**暂停子 agent，回本 session 报告**：

- W1 产物缺失 ≥ 3 个（说明 W0 后台任务调度有问题）
- W2/W3 子 agent 报告发现 6 个决策之间有冲突
- W2/W3 子 agent 建议修改决策（不允许在执行阶段改决策，要回评审 session 走变更流程）
- W4 集成时发现 mandatory echo 实现成本超出预算
- AI 成本突破决策 5 的硬红线（单局 ¥0.8 / 20 次主调用）

---

## 7. 完成标准

W4 完成的标志：

- [ ] 30-45 分钟单局可从头到尾跑通（无报错、可存档、可重演）
- [ ] 玩家在 photo_lab_2008 的行为能在 reunion_2024 触发 mandatory echo
- [ ] 4 项自检 CI 100% 拦截违规互动
- [ ] 4 级降级链 4 个等级都能演示
- [ ] 至少 5 个外部用户完成端到端体验
- [ ] 单局 AI 成本 < ¥0.8
- [ ] 决策 1-6 所有验收标准全部满足

满足以上后，本任务可以标记为 "W4 通过 · 准备进入内容规模化"。

---

## 附：决策源文件路径

`D:/G1-ai-native/docs/design/requirements-review-v1.md` —— **每次启动新子 agent 都把这条路径 + 决策编号 + 验收标准贴到子 agent 的 prompt 顶部**。
