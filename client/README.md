# 革命街没有尽头 · AI 原生重构版 — Electron 客户端

外部可分享版。电影感 UI · 旁观者 UX · 付费点 UX。

## 启动

```bash
pnpm install
pnpm dev            # 浏览器预览（Vite + React）
pnpm dev:all        # 同时启动 Vite + Electron
pnpm build:win      # 打包 Windows NSIS 安装包
pnpm build:mac      # 打包 macOS DMG（arm64 + x64）
pnpm build:linux    # 打包 Linux AppImage
```

需要 Node 20+。第一次 `pnpm install` 后会自动安装 Electron 33。

## 决策依据

- `../docs/design/requirements-review-v1.md` — 6 个核心决策的**唯一权威源**
- `../docs/design/brief-for-dev-task-v1.md` — 综合开发任务启动 brief

## 严格遵守的决策红线

| 决策 | 验证位置 |
|---|---|
| 决策 2：默认 = 旁观者 | `lib/store.ts` → `povMode: "observer"`；`POVSwitcher.tsx` 强制默认 |
| 决策 2：付费解锁视角 | `commerce/POVUnlock.tsx` ¥3 / 段；`commerce/CollectorsView.tsx` 包含双视角 |
| 决策 2：旁白"你看到了 X" | `features/observer/ObserverNarration.tsx` 强制前缀 |
| 决策 2：解锁后换叙事 | `archive/Memories.tsx` 角色视角多一段独白 |
| 决策 4：付费门从「已结束」触发 | `lib/store.ts` → `canOpenPaywallInState()`；`commerce/PaywallOverlay.tsx` 强制 |
| 决策 5：P95 < 4s | `lib/api.ts` FAST_TIMEOUT_MS = 1.5s, TIMEOUT_MS = 8s |
| 决策 5：单回合 ≤ 2 次 LLM | `lib/useSceneRunner.ts` 每次只调 1 次 |
| 决策 5：4 级降级链 | `lib/api.ts` L1-L4；`components/DegradationBadge.tsx` 视觉反馈 |

## 目录结构

```
client/
├── electron/                 # Electron 壳
│   ├── main.ts               # 主进程（窗口 / 菜单 / IPC）
│   ├── preload.ts            # 预加载脚本
│   └── tsconfig.json         # CommonJS 编译
├── src/
│   ├── audio/                # 声音引擎（基于 v6 audio-engine.ts）
│   ├── components/           # 共享 UI
│   │   ├── AppShell.tsx
│   │   ├── CinematicFrame.tsx
│   │   ├── ActionBar.tsx
│   │   ├── InvestigationPanel.tsx
│   │   ├── NPCReactions.tsx
│   │   ├── SceneTimeJump.tsx
│   │   ├── SceneStatusBar.tsx
│   │   ├── DegradationBadge.tsx
│   │   ├── ErrorBoundary.tsx
│   │   └── TitleBar.tsx
│   ├── features/
│   │   ├── observer/         # 决策 2：旁观者 UX
│   │   │   ├── ObserverNarration.tsx
│   │   │   ├── ObserverCamera.tsx
│   │   │   ├── ObserverHint.tsx
│   │   │   └── POVSwitcher.tsx
│   │   ├── scenes/           # 三场景
│   │   │   ├── PhotoLab2008.tsx
│   │   │   ├── Farewell2011.tsx
│   │   │   └── Reunion2024.tsx
│   │   ├── archive/          # 决策红线：卷宗
│   │   │   ├── ArchivePage.tsx
│   │   │   ├── Timeline.tsx
│   │   │   ├── Evidence.tsx
│   │   │   ├── Artifacts.tsx
│   │   │   ├── Memories.tsx  # 决策 2：解锁视角后多一段独白
│   │   │   ├── CausalSeeds.tsx
│   │   │   └── Replay.tsx
│   │   ├── commerce/         # 决策 4：7 个商品
│   │   │   ├── Paywall.tsx
│   │   │   ├── paywallProducts.ts
│   │   │   ├── PaywallOverlay.tsx
│   │   │   ├── PassportView.tsx
│   │   │   ├── CollectorsView.tsx
│   │   │   ├── ParallelOps.tsx
│   │   │   ├── Credits.tsx
│   │   │   ├── POVUnlock.tsx
│   │   │   └── Keepsake.tsx
│   │   ├── settings/
│   │   │   └── SettingsPage.tsx
│   │   └── start/
│   │       └── StartPage.tsx
│   ├── lib/
│   │   ├── api.ts            # SSE / REST / 4 级降级
│   │   ├── store.ts          # Zustand 状态
│   │   └── useSceneRunner.ts # 场景共享 hook
│   ├── mocks/                # 无服务端时的 mock 数据
│   │   └── scenes.ts
│   ├── styles/               # 电影感 / 字体 / 动效
│   │   ├── cinematic.css
│   │   ├── typography.css
│   │   └── animations.css
│   ├── types/
│   │   ├── schemas.ts        # 8 个 JSON Schema 的 TS 类型
│   │   └── global.d.ts
│   ├── App.tsx
│   ├── main.tsx
│   └── router.tsx
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
├── electron-builder.json
├── tsconfig.json
└── electron/tsconfig.json
```

## 11 个核心模块

| # | 模块 | 路径 |
|---|---|---|
| 1 | Electron 壳 | `electron/main.ts` `electron/preload.ts` `electron-builder.json` |
| 2 | React 应用 | `src/App.tsx` `src/main.tsx` `src/router.tsx` |
| 3 | 旁观者 UX | `src/features/observer/*` |
| 4 | 三场景 UI | `src/features/scenes/*` |
| 5 | 卷宗与档案 | `src/features/archive/*` |
| 6 | 付费墙 | `src/features/commerce/*` |
| 7 | 视觉规范 | `src/styles/*` `tailwind.config.js` |
| 8 | 声音集成 | `src/audio/AudioEngine.ts` |
| 9 | API 客户端 | `src/lib/api.ts` |
| 10 | 状态管理 | `src/lib/store.ts` |
| 11 | 可访问性 | `src/styles/a11y.test.ts` 内联清单 |

## Mock 模式

不联调服务端时：

- `lib/api.ts` → `mockSubmitTurn()` 内置 6 种 NPC 反应
- `mocks/scenes.ts` → 三个场景的 SceneMeta（与 YAML 对齐）
- 启动页直接可用：`http://localhost:5173`

## 联调服务端

在 `.env` 或启动时设置：

```bash
VITE_API_BASE=http://localhost:8000 pnpm dev
```

服务端需实现：

- `GET /health`
- `GET /scenes/{sceneId}` → `SceneMeta`
- `GET /runs/{runId}/snapshot` → `WorldSnapshot`
- `POST /turns` (SSE) → 事件流：`npc_partial` / `npc_final` / `director` / `resolver` / `degraded` / `done`

## 美术资源

来自 `_legacy_v6/public/art-v5/` 的 10 张 canonical 资产。`electron-builder.json` 已配置 extraResources 把 art-v5 打包到 `resources/art-v5/`。

## 类型严格性

8 个 JSON Schema 全部在 `src/types/schemas.ts` 转为 TypeScript 类型。客户端不持有权威状态，所有状态变化都从服务端获取的 `ResolverOutcome` 推导。

## 已知未做

- BYOK（决策 4：本版不做 P1）
- 真支付集成（mock 流程）
- 服务端联调（mock 模式可用）
- 多语言：当前 zh-CN 主，en 预留
