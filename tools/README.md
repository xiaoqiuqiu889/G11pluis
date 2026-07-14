# tools/ — content-toolchain for 《革命街没有尽头》 AI 原生重构

> **P0 决策依据**：本目录是决策 6（"4 项自检落成工具"）的落成产物。
> 任何对 `content/**/scenes/*` 的改动都必须通过本目录的 4 项自检工具，
> 否则 CI 阻断。

## 目录结构

```
tools/
├── four_questions_guard_lib.py     # 4 项自检核心库（100% 单测覆盖）
├── four-questions-guard.py         # 4 项自检 CLI（决策 6 必含）
├── run_content_studio.py           # content-studio 启动器
├── run_replay_lab.py               # replay-lab 启动器
│
├── content-studio/                 # FastAPI + 单页 Web（决策 6 嵌入点）
│   ├── server.py
│   └── ui/index.html
│
├── replay-lab/                     # 快照重放工具
│   ├── replay.py                   # 核心 reducer
│   ├── cli.py                      # 命令行
│   ├── web.py                      # FastAPI
│   └── ui/index.html
│
├── batch-simulator/                # 批量模拟器
│   └── simulator.py
│
└── ci/                             # CI 集成
    ├── README.md
    ├── .github/workflows/four-questions.yml
    └── .gitlab-ci.yml
```

## 4 个工具概览

### 1. `four-questions-guard.py`（**P0**）

**作用**：CI/编辑器层面的 4 项自检守门员。

**用法**：
```bash
# 单文档
python tools/four-questions-guard.py content/.../scenes/photo_lab_2008.yaml

# 多文档
python tools/four-questions-guard.py content/**/scenes/*.yaml

# 仅 JSON（CI 友好）
python tools/four-questions-guard.py --json scene.yaml

# 仅人类可读
python tools/four-questions-guard.py --human scene.yaml

# 限定检查集
python tools/four-questions-guard.py --checks Q1,Q4 --quiet scene.yaml
```

**9 项检查**（4 核心 + 3 附加 + 2 mandatory echo）：

| ID | 来源决策 | 含义 |
|----|----------|------|
| Q1_changes_world_state | 决策 1 | 改变世界状态（artifact / event） |
| Q2_changes_character_knowledge | 决策 1 | 改变人物认知（belief / memory） |
| Q3_changes_available_actions | 决策 1 | 改变后续可用行动（turn_budget / action_whitelist） |
| Q4_creates_future_echo | 决策 1 | 产生未来回响（causal_seed / far_echo_routes） |
| A_forbidden_reveal_risk | 决策 6 | 违反 forbidden_reveals 列表 |
| B_turn_budget_safe | 决策 6 | turn 数不超出 max_turns |
| C_artifact_uniqueness | 决策 6 | artifact 归属唯一 |
| D_mandatory_echo_declared | 决策 3 | 场景合同显式登记 mandatory echo |
| E_npc_recall_within_mandatory | 决策 3 | NPC 主动提起的回响必须在 mandatory 列表里 |

**退出码**：
- `0` — 全部通过
- `1` — 至少一份文档阻断
- `2` — I/O 错误

**单测覆盖**：核心库 `four_questions_guard_lib.py` **100%**（149 个测试）。
包含 brief 要求的 7 个场景：passing / blocking(Q1-Q4 各自) / forbidden_reveal / turn_budget 超出 / artifact 重复 / mandatory echo 缺失 / mandatory echo 与 NPC recall 不一致。

### 2. `content-studio/`（决策 6 嵌入点）

**作用**：策划工作站。单页 Web 工具，编辑人物卡 / 客观事实和秘密 / 叙事合同 / 场景节拍白名单 / 行为成本和状态变化。提交时自动跑 4 项自检。

**启动**：
```bash
python tools/run_content_studio.py --port 8765
# 浏览器打开 http://127.0.0.1:8765
```

**API 端点**：
- `GET  /api/health`       — 健康检查
- `GET  /api/cases`        — 列出所有 case
- `GET  /api/file`         — 读文件
- `POST /api/guard`        — 对磁盘文件跑 guard
- `POST /api/guard-text`   — 对 in-memory YAML/JSON 跑 guard（UI 主用）
- `POST /api/save`         — 保存（自动跑 guard）

### 3. `replay-lab/`（任意快照重跑）

**作用**：从初始 world snapshot 出发，按 eventSequence 顺序应用 ResolverOutcome
delta，得到最终 snapshot + per-event trace。可选地用 4 项自检装饰每条 trace。

**CLI 用法**：
```bash
# 基本重放
python tools/replay-lab/cli.py --events events.yaml

# 显式 snapshot
python tools/replay-lab/cli.py \
    --snapshot snapshot.json \
    --events   events.yaml \
    --output   replay.json

# 重放到 eventSequence=10 为止
python tools/replay-lab/cli.py --events events.yaml --stop-at 10

# 同时跑 4 项自检（用 guard 装饰每条 trace）
python tools/replay-lab/cli.py --events events.yaml --guard
```

**Web 启动**：
```bash
python tools/run_replay_lab.py --port 8766
```

### 4. `batch-simulator/`（批量模拟 100-1000 局）

**作用**：N 次合成游戏跑一份场景合同，统计：
- 阻断率
- 平均 / 中位 / 最大 turn 数
- action 分布
- end_kind 分布
- forbidden_reveals 触达
- artifact 分布

**用法**：
```bash
# 随机策略 100 局
python tools/batch-simulator/simulator.py \
    --contract content/.../scenes/photo_lab_2008.yaml \
    --policy random \
    --n 100 \
    --output batch.json

# 启发式策略 1000 局
python tools/batch-simulator/simulator.py \
    --contract scene.yaml \
    --policy heuristic \
    --n 1000

# 不带 per_play（更小的输出）
python tools/batch-simulator/simulator.py \
    --contract scene.yaml \
    --n 500 \
    --no-per-play
```

**策略**：`random` / `heuristic` / `ai`（后两者是 stub，待 W3-A 真实 model gateway）。

## CI 集成

`tools/ci/` 包含 GitHub Actions 和 GitLab CI 两份配置，触发条件是
`content/**/scenes/*` 的任何改动。

GitHub Actions 步骤：
1. checkout
2. setup Python 3.12
3. `pip install pyyaml pytest coverage fastapi uvicorn httpx`
4. `pytest tests/adversarial/test_four_questions_guard.py`
5. 检测改动的 scene 文件
6. `python tools/four-questions-guard.py <changed-files>`
7. 退出码 != 0 → 阻断 PR

## 测试

```bash
# 全部
python -m pytest tests/adversarial/ -v

# 单独跑某个工具的测试
python -m pytest tests/adversarial/test_four_questions_guard.py -v
python -m pytest tests/adversarial/test_content_studio.py -v
python -m pytest tests/adversarial/test_replay_lab.py -v
python -m pytest tests/adversarial/test_batch_simulator.py -v

# 覆盖率
python -m coverage run --include='tools/*' -m pytest tests/adversarial/
python -m coverage report
```

## 红线复核

- ✅ `four-questions-guard.py` 是 P0 CLI 工具，已落成
- ✅ 嵌入 `content-studio`（每次提交自动跑）
- ✅ 嵌入 CI（PR 改 `content/**/scenes/*` 触发）
- ✅ 工具运行失败 → CI 阻断（退出码 1）
- ✅ mandatory echo 缺失 → guard 阻断
- ✅ 4 项核心 + 3 项附加 + 2 项 mandatory echo = 9 项检查
- ✅ 输出含人类可读解释（不只是 yes/no）
- ✅ 单测覆盖核心库 100%
