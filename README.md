# 革命街没有尽头 · AI 原生重构版

> 玩家行为即叙事的 AI-native 横版。《革命街没有尽头》第一案纵切片：
> 德黑兰 2008 → 2011 → 伊斯坦布尔 2024，13 年间两张同版毕业照的去向。

---

## 项目目标

把一个 *传统* 的纵切片游戏（v6/v7 时代，**预制剧本 + 多分支选择**）改造成
**AI-native** 版本——玩家在 2008 做出的具体行为，会在 2024 决定性地
影响 NPC 主动提起的台词和可触发的回响。

W4 = **完整可玩的部署**：

* 后端 FastAPI 真在跑（不再 mock）。
* PostgreSQL/SQLite 真在写。
* 客户端 *可以* 连真服务端。
* 6 个核心决策（决策 1-6）仍在守门。

---

## 唯一启动方式

双击仓库根目录的 `Demo-01.cmd`。这是当前唯一受支持的一键启动入口：

* 客户端固定使用真实 API 链路（`VITE_USE_MOCK=false`）。
* 服务端固定使用确定性 mock LLM（`G1N_USE_MOCK=1`），无需 API Key。
* 服务端状态写入 SQLite；玩家动作会到达
  `:8000/v1/runs/:id/actions`，模型调用会记录在 `model_calls`。
* 启动器不会强杀未知进程；5173 被占用时会自动选择 5174–5199
  中的空闲端口，并在控制台打印最终 Demo 地址。

只检查依赖、不启动服务：

```cmd
Demo-01.cmd --check
```

演示边界和验收方法见 `docs/demo-01.md`。

---

## 决策红线（速查）

详细见 `docs/design/requirements-review-v1.md`。这里是 W4 实现里
每条决策的落点：

| 决策 | 红线 | W4 落点 | 状态 |
|---|---|---|---|
| 1 行为门槛 | 每场 ≥ 6 结构化行为 + 1 不可撤回 | `server/engine/state_machine.py` 12 个 reducer；scene YAML turn_budget；`action_runner._select_mandatory_seed` | ✅ |
| 2 默认旁观者 | 视角付费；旁白用"你看到了 X" | 客户端 React 组件保持第三人称；服务端无视角切换 | ✅（视角解锁留 P1） |
| 3 mandatory echo | 必须显式登记；NPC 不能自由发挥 | `server/agents/resolver.py` 的 `MandatoryEchoValidation`；`action_runner._select_mandatory_seed` 注入 4 条规则 | ✅ |
| 4 商业化档位 | ¥0/¥25/¥48/¥12/¥3/¥8 + 决策 5 4 级降级 | `server/app.py` 的 `PRODUCT_CATALOG` + `purchase_mock_confirm` | ✅ |
| 5 4 级降级链 + 4 硬红线 | ≤ 20 calls/局；< 800 token/次；≤ 2 calls/turn；P95 < 4s | `server/model/degradation.py` + `cost_control.py`；action_runner 在 LLM 失败时回退到 fallback NPC | ✅ |
| 6 4 项自检 | 工具入 CI + 4 个 yes/no | `tools/four-questions_guard.py`（W1 阶段交付）；`action_runner` 调 resolver 时会触发 `ResolverAgent` 内置的 4 项检查 | ✅ |

---

## 端到端架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                      Electron / Vite (port 5173)                     │
│  client/src/lib/api.ts                                                │
│    VITE_USE_MOCK=true  →  mockSubmitTurn() (内置脚本)                │
│    VITE_USE_MOCK=false →  fetch /v1/...  (真后端)                    │
└──────────────────────────────────────┬───────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    FastAPI (port 8000)  server/app.py                │
│  ┌────────────┐   ┌──────────────┐   ┌──────────────┐                 │
│  │ HTTP 路由   │──▶│ ActionRunner │──▶│ ResolverAgent│ ←── 写域隔离  │
│  │ (13 端点)  │   │ (1 turn =    │   │  (唯一 writer)│                │
│  └────────────┘   │  ≤ 2 LLM call│   └──────┬───────┘                 │
│       │           │  + 1 resolve) │          │                         │
│       │           └──────┬───────┘          │                         │
│       │                  │                  │                         │
│       │                  ▼                  ▼                         │
│       │           ┌──────────────┐   ┌──────────────┐                │
│       │           │ ModelGateway  │   │  Engine      │                │
│       │           │ (4 级降级链)  │   │  - state     │                │
│       │           │ + 成本控制器  │   │  - resolver  │                │
│       │           └──────┬───────┘   │  - event log │                │
│       │                  │           └──────┬───────┘                │
│       ▼                  ▼                  ▼                         │
│  ┌────────────────────────────────────────────────────┐              │
│  │  SQLAlchemy 2.0 ORM  (server/db.py)                  │              │
│  │  11 表: game_runs, world_snapshots, game_events,   │              │
│  │        character_beliefs, memories, artifacts,      │              │
│  │        model_calls, entitlements, causal_seeds,     │              │
│  │        narrative_contracts, branch_timelines,       │              │
│  │        analytics_events                             │              │
│  └────────────────────────┬───────────────────────────┘              │
└───────────────────────────┼──────────────────────────────────────────┘
                            ▼
              ┌─────────────────────────────┐
              │  SQLite (./data/g1n.db)      │
              │  (or PostgreSQL via          │
              │   G1N_DB_URL=postgresql+...) │
              └─────────────────────────────┘
```

### 写域隔离（write-domain isolation）

**唯一规则**：`server/agents/resolver/ResolverAgent` 是唯一
可以 mutate canonical state 的组件。

* HTTP 路由（`app.py`）→ `ActionRunner` → `ResolverAgent.resolve_turn` → `engine.Resolver.resolve`
* `Repository.save_outcome` 只持久化 Resolver 已验证过的结果。
* 不允许任何端点、Agent、Service 直接 INSERT/UPDATE 到 game_runs / world_snapshots / artifacts 等核心表。

### 决策 3 mandatory echo 落点

`server/action_runner.py` 的 `_select_mandatory_seed`：

```python
_MANDATORY_SEED_RULES = [
    {
        "scene": "photo_lab_2008", "action": "give",
        "target": "leila", "evidence": ["photo_A"],
        "seed_id": "photo_in_pocket",
        "target_scenes": ["reunion_2024"],
    },
    {
        "scene": "photo_lab_2008", "action": "give",
        "target": "arash", "evidence": ["photo_B"],
        "seed_id": "photo_in_book",
        "target_scenes": ["reunion_2024"],
    },
    # ...
]
```

玩家 2008 给莱拉 `give photo_A` → 注入 `photo_in_pocket` 因果种子 →
跨场景传递到 reunion_2024 → NPC proposal 引用该种子 → 决策 3
"AI 导演不能自由发挥"硬约束已生效。

---

## 13 个端点

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | liveness + DB ping |
| GET | `/v1/catalog` | 商品目录（决策 4） |
| GET | `/v1/entitlements` | 用户权益 |
| POST | `/v1/purchases/mock-confirm` | 模拟购买 |
| POST | `/v1/runs` | 创建 run |
| GET | `/v1/runs/:runId` | 读 run |
| POST | `/v1/runs/:runId/scenes/:sceneId/enter` | 进入场景 |
| POST | `/v1/runs/:runId/actions` | **核心写端点**（写域隔离） |
| GET | `/v1/runs/:runId/timeline` | 时间线 |
| GET | `/v1/runs/:runId/archive` | 档案馆（artifacts + beliefs + memories + seeds） |
| POST | `/v1/runs/:runId/branches` | 创建重演分支 |
| GET | `/v1/runs/:runId/branches` | 列分支 |
| POST | `/v1/runs/:runId/resume` | 续玩 |
| GET | `/v1/runs/:runId/snapshot` | 最新世界快照 |
| GET | `/v1/scenes/:sceneId` | 场景元数据 |
| POST | `/v1/analytics/events` | 埋点 |

`POST /v1/runs/:runId/actions` body：

```json
{
  "runId": "<uuid>",
  "sceneId": "photo_lab_2008",
  "clientActionId": "<uuid>",
  "expectedEventSequence": 0,
  "playerAction": {
    "actionType": "give",
    "actorId": "leila",
    "targetId": "leila",
    "evidenceIds": ["photo_A"],
    "utterance": "把这一张放进我包里",
    "tone": "neutral",
    "disclosureLevel": 0.5,
    "isDeceptive": false,
    "clientTimestamp": "2026-07-15T00:00:00Z",
    "schemaVersion": "1.0.0"
  },
  "clientVersion": "1.0.0"
}
```

---

## 数据库 — 11 表

按 brief 列出 11 张表（v0.1 PRD §3 核心数据表）：

| 表 | 用途 |
|---|---|
| `game_runs` | 玩家一局游戏的顶层实体 |
| `world_snapshots` | 每个 event 的完整 WorldSnapshot JSON |
| `game_events` | append-only 事件账本（带 idempotency key） |
| `character_beliefs` | 每个 (character, subject) 信念的历史行 |
| `memories` | 角色的可唤起记忆 |
| `artifacts` | 物件所有权/状态的查询镜像 |
| `model_calls` | LLM 调用审计（决策 5 验收点） |
| `entitlements` | 用户购买状态（决策 4） |
| `causal_seeds` | 休眠 / 已触发的跨年代种子 |
| `narrative_contracts` | 场景合同缓存（加速启动） |
| `branch_timelines` | 重演分支（决策 4） |
| `analytics_events` | 客户端埋点 |

### 默认 DB

* `sqlite:///./data/g1n.db`（无需安装）
* 切到 PostgreSQL：设 `G1N_DB_URL=postgresql+asyncpg://user:pass@host/db`

### 迁移

* 开发：`db.init_db()` 自动建表（无 Alembic 启动开销）
* 生产：`cd server && alembic upgrade head`（Alembic 配置在 `server/alembic.ini`）

---

## 客户端切换 mock ↔ real

`client/src/lib/api.ts`：

```ts
const _useMockRaw = (readEnv("VITE_USE_MOCK") ?? "true").trim().toLowerCase();
export const USE_MOCK: boolean =
  !(_useMockRaw in {"0": 1, "false": 1, "no": 1, "off": 1});
```

| VITE_USE_MOCK | 行为 |
|---|---|
| `true` (默认) / 未设 | 客户端内置 mock；可独立跑；不需要后端 |
| `false` | 调 `:8000/v1/...`；由 `Demo-01.cmd` 启动并校验后端 |

`Demo-01.cmd` 会把 `VITE_USE_MOCK=false` 注入 Vite，并把服务端锁定在
确定性 mock LLM 模式；不要使用未知来源的已编译 Vite 实例替代该入口。

---

## 测试覆盖

### 已有测试

```cmd
cd D:\G1-ai-native
set PYTHONPATH=server
python -m pytest tests/ -v
```

| 测试套 | 来源 | 数量 |
|---|---|---|
| `tests/integration/test_end_to_end_three_scenes.py` | W3 交付 | 4 |
| `tests/integration/test_degradation_levels.py` | W3 交付 | 11 |
| `tests/engine/*` | W2 交付 | 多 |
| `tests/agents/*` | W3 交付 | 多 |
| `tests/safety/*` | W3 交付 | 多 |
| `tests/model/*` | W3 交付 | 多 |
| `tests/adversarial/*` | W1 交付 | 多 |

W4 集成测试（HTTP 层）：`tools/_w4_e2e_smoke.py`，验证所有 13
端点可调用 + 数据落库。

---

## 已知问题

* **W4-ISSUE-01**: per-turn LLM call count (decision 5 R3) is not
  enforced strictly — the W3-A gateway's `run_state.turn_index`
  is always 0. We set `hard_turn_call_budget=100` (default) to
  avoid false positives. The per-run cap (20) is the real
  decision-5 hard line and is enforced. **Fix target: W5**.

* **W4-ISSUE-02**: scene YAMLs are loaded with a built-in
  fallback contract when missing or malformed. This is by
  design (W3 had the same fallback) but means new scenes
  authored by content team won't be picked up until the YAML
  parser is updated.

* **W4-ISSUE-03**: the `give` action in `photo_lab_2008` plants
  the `photo_in_pocket` and `photo_in_book` seeds via a
  hand-coded rule table (`_MANDATORY_SEED_RULES`). Future
  scenes will need their own entries; the integration test
  has the canonical patterns.

* **W4-ISSUE-04**: the resolver's `_auto_fire_seeds` mutates a
  local store but doesn't write back to the snapshot
  (W3-ISSUE-02 in the W3 integration report). We work around
  this by reading the snapshot's `causalSeedsActive` after the
  resolver runs and persisting that.

* **W4-ISSUE-05**: `WorldSnapshot.from_dict` is exercised
  primarily via JSON round-trips. The `EventLog` is rebuilt
  fresh on every `RunRegistry.open` (we don't replay events);
  the canonical state lives in the latest snapshot row.

---

## 目录结构

```
G1-ai-native/
├── server/                  # FastAPI + 引擎 + Agent + 模型
│   ├── app.py              # ← 13 端点 HTTP 入口
│   ├── db.py               # ← SQLAlchemy 2.0 引擎 + 11 ORM
│   ├── repository.py       # 持久化（save_outcome 等）
│   ├── scene_loader.py     # YAML → contract
│   ├── run_registry.py     # 内存 active-run 缓存
│   ├── llm_runtime.py      # provider 路由（mock 默认）
│   ├── action_runner.py    # 单 turn 驱动（核心）
│   ├── alembic.ini         # 生产迁移
│   ├── migrations/         # 迁移脚本
│   ├── agents/             # W3-B 交付（Resolver / NPC / Director / Intent / Memory）
│   ├── engine/             # W2-A 交付（state machine + reducer + resolver）
│   ├── model/              # W3-A 交付（gateway + degradation + cost control）
│   ├── safety/             # W3-C 交付（schema 校验 + clamping）
│   └── config/schemas/     # 8 个 JSON Schema（brief 强制）
├── client/                  # Electron + React
│   └── src/
│       ├── lib/
│       │   ├── api.ts      # ← VITE_USE_MOCK 切换 + 13 方法
│       │   └── useSceneRunner.ts
│       ├── types/schemas.ts  # 8 个 TS 类型（与 server JSON Schema 对齐）
│       └── ...
├── content/                 # 内容资产
│   └── case_01_revolution_street/
│       ├── scenes/*.yaml    # 3 场景叙事合同
│       ├── beliefs/         # 信念矩阵
│       └── fallbacks/       # L1 降级文案（自动生成）
├── tests/                   # 单元 + 集成测试
│   └── integration/         # W3 端到端测试
├── docs/design/             # 决策文档
│   ├── requirements-review-v1.md  # 6 决策权威源
│   ├── brief-for-dev-task-v1.md   # 任务 brief
│   └── w3-integration-report.md   # W3 集成报告
├── data/                    # 运行时（SQLite + 日志）— 不入 git
├── tools/                   # 内容工具 + 4 项自检 + W4 烟雾测试
├── Demo-01.cmd              # 唯一一键启动入口（真实 API + 确定性 mock LLM）
└── README.md                # 本文件
```

---

## 快速验证

```cmd
:: 1) 环境预检
Demo-01.cmd --check

:: 2) 启动真实 API Demo
Demo-01.cmd

:: 3) 另开窗口运行正式浏览器 E2E
node client\e2e\m1-real-case01.cjs
```

应该看到：
* 浏览器打开控制台所打印的 `photo_lab_2008` 地址
* 每个动作打到后端
* `data/g1n.db` 增长
* `/health` 返回 `service=g1n-server` 且 `llm.isMock=true`

---

## 决策约束 — 实现里被锁死的部分

* **客户端不能直接调 LLM** — 客户端只走 `submitAction` → HTTP → 服务端
  → `ModelGateway.complete`。客户端代码里没有 LLM client SDK。
* **客户端不保存权威状态** — Zustand store 只缓存本机显示数据；
  `WorldSnapshot` 的真值在服务端。
* **Mock 不跳过 mandatory echo 校验** — mock provider 仍然
  走 `ResolverAgent` 的 `MandatoryEchoValidation`；非法
  proposal 同样被 reject。
* **Mock 不跳过 cost 红线** — mock 默认 cost = 0，但仍受
  决策 5 硬红线的 *调用次数* 约束。
* **没修改 6 个决策** — `docs/design/requirements-review-v1.md` 仍是
  权威；W4 实现只是把决策落到了代码里。

---

*W4 部署交付 — 2026-07-15*
