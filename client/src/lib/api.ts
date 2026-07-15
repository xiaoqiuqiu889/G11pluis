// =============================================================================
// 革命街没有尽头 · API 客户端
// -----------------------------------------------------------------------------
// 与 FastAPI 服务端通信：流式响应（SSE / EventSource）+ REST
// 决策 5：单回合模型调用 ≤ 2 次；P95 < 4s；4 级降级链必须有视觉反馈。
//
// 模式切换：
//   VITE_USE_MOCK=true  (default)  → 客户端内置 mock，无需服务端
//   VITE_USE_MOCK=false             → 走真实 FastAPI 后端 (port 8000)
// =============================================================================

import type {
  ActionType,
  DegradationLevel,
  InvestigatableObject,
  NpcProposal,
  PlayerAction,
  Product,
  ResolverOutcome,
  RunState,
  SceneId,
  SceneMeta,
  Tone,
  WorldSnapshot,
} from "@/types/schemas";
import { useStore } from "./store";

// -----------------------------------------------------------------------------
// 配置
// -----------------------------------------------------------------------------

/** Read a Vite env var at module load time.  Undefined in
 * non-Vite environments (e.g. the production build's
 * unit tests), in which case the default applies. */
function _readEnv(name: string): string | undefined {
  try {
    if (typeof import.meta !== "undefined") {
      const env = (import.meta as unknown as { env?: Record<string, string> }).env;
      if (env && typeof env[name] === "string") return env[name];
    }
  } catch {
    // import.meta may not exist in test environments.
  }
  if (typeof window !== "undefined") {
    const w = window as unknown as Record<string, string | undefined>;
    if (w[`__${name}__`]) return w[`__${name}__`];
  }
  return undefined;
}

const API_BASE: string =
  _readEnv("VITE_API_BASE") ||
  (typeof window !== "undefined" && (window as unknown as { __API_BASE__?: string }).__API_BASE__) ||
  "http://localhost:8000";

/** Mock-mode switch.
 *
 *  Default = mock (no API key, no server required).  Set
 *  ``VITE_USE_MOCK=false`` to call the real server.
 *
 *  Allowed truthy values: ``"1"``, ``"true"``, ``"yes"``,
 *  ``"on"`` (case-insensitive).
 */
const _useMockRaw = (_readEnv("VITE_USE_MOCK") ?? "true").trim().toLowerCase();
export const USE_MOCK: boolean =
  !(_useMockRaw in {"0": 1, "false": 1, "no": 1, "off": 1});

const TIMEOUT_MS = 8_000;                 // 决策 5：客户端侧兜底
const FAST_TIMEOUT_MS = 1_500;            // L1 软超时（NPC 反应兜底）
const P95_BUDGET_MS = 4_000;              // 决策 5 红线

// -----------------------------------------------------------------------------
// 内部：HTTP helper
// -----------------------------------------------------------------------------

async function httpJson<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
  timeoutMs: number = TIMEOUT_MS,
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const init: RequestInit = {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    signal: AbortSignal.timeout(timeoutMs),
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }
  const r = await fetch(url, init);
  if (!r.ok) {
    let detail = "";
    try {
      detail = (await r.json())?.detail || r.statusText;
    } catch {
      detail = r.statusText;
    }
    throw new Error(`HTTP ${r.status} ${path}: ${detail}`);
  }
  return (await r.json()) as T;
}

// -----------------------------------------------------------------------------
// 类型：客户端回合
// -----------------------------------------------------------------------------

// -----------------------------------------------------------------------------
// 类型：客户端回合
// -----------------------------------------------------------------------------
export interface TurnRequest {
  action: PlayerAction;
  observedObjects?: InvestigatableObject[];
}

export interface TurnResponse {
  outcome: ResolverOutcome;
  npcProposals?: NpcProposal[];
  clientActionId: string;
  degraded: DegradationLevel;
  fallbackUsed: boolean;
  latencyMs: number;
  // 客户端打字机分段（resolver resolvedText 直接送入 UI）
  resolvedText: string;
}

export interface StreamEvent {
  type: "npc_partial" | "npc_final" | "director" | "resolver" | "error" | "done";
  payload: unknown;
}

// =============================================================================
// 4 级降级链（决策 5）
// =============================================================================

/**
 * L1：NPC 反应超时（> 1.5s 未开始流式）→ 策划兜底台词
 * L2：Director 超时 → 跳过节拍校验，只跑 NPC Proposal
 * L3：Resolver 之前任何一步二次失败 → 主线走策划脚本（不调 LLM）
 * L4：Resolver 写库失败 → 弹"服务暂不可用"+ 保留存档
 */
const FALLBACK_LINES: Record<string, string> = {
  npc_silent: "（他/她没有立刻回答——灯泡下，能听到放映机的低频转动。）",
  npc_deflect: "（他/她只是轻轻把视线移开，像是在保护某样东西不被你看见。）",
  npc_pause: "（一段沉默之后，他/她开口，声音比预想中更轻。）",
};

function pickFallback(intent?: string): string {
  if (intent && /deflect|silent|denied/.test(intent)) return FALLBACK_LINES.npc_deflect;
  if (intent && /comfort|admit|plead/.test(intent)) return FALLBACK_LINES.npc_pause;
  return FALLBACK_LINES.npc_silent;
}

// =============================================================================
// UUID 与工具
// =============================================================================

export function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  // RFC 4122 fallback
  const hex = (n: number) => n.toString(16).padStart(2, "0");
  const r = Array.from({ length: 16 }, () => Math.floor(Math.random() * 256));
  r[6] = (r[6] & 0x0f) | 0x40;
  r[8] = (r[8] & 0x3f) | 0x80;
  return [
    hex(r[0]) + hex(r[1]) + hex(r[2]) + hex(r[3]),
    hex(r[4]) + hex(r[5]),
    hex(r[6]) + hex(r[7]),
    hex(r[8]) + hex(r[9]),
    hex(r[10]) + hex(r[11]) + hex(r[12]) + hex(r[13]) + hex(r[14]) + hex(r[15]),
  ].join("-");
}

// =============================================================================
// 健康检查
// =============================================================================

export async function pingServer(): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/health`, { method: "GET", signal: AbortSignal.timeout(2_000) });
    return r.ok;
  } catch {
    return false;
  }
}

// =============================================================================
// 真实服务端 — Brief 强制要求的方法（V1 接口集）
// -----------------------------------------------------------------------------
// 全部对应 server/app.py 里的端点。
// 默认情况下（USE_MOCK = true）这些方法在客户端不被调用 — useSceneRunner
// 直接走 mockSubmitTurn。但 useSceneRunner 的 决策切换 函数会调它们。
// =============================================================================

export interface RunDto {
  runId: string;
  userId: string;
  caseSlug: string;
  currentSceneId: string;
  era: string;
  eventSequence: number;
  phase: string;
  endingId: string | null;
  startedAt: string | null;
  lastActiveAt: string | null;
  endedAt: string | null;
  isArchived: boolean;
  isMock: boolean;
  schemaVersion: string;
}

export interface ActionRequestBody {
  runId: string;
  sceneId: string;
  clientActionId: string;
  expectedEventSequence: number;
  playerAction: PlayerAction;
  clientVersion?: string;
}

export interface ActionResponseBody {
  ok: boolean;
  outcome: ResolverOutcome;
  snapshot: WorldSnapshot;
  clientActionId: string;
  eventSequence: number;
  degraded: DegradationLevel | "none";
  fallbackUsed: boolean;
  latencyMs: number;
  resolvedText: string;
  modelCalls: Array<Record<string, unknown>>;
  degradedToL3: boolean;
}

export interface TimelineResponse {
  runId: string;
  count: number;
  events: Array<Record<string, unknown>>;
}

export interface ArchiveResponse {
  runId: string;
  artifacts: Array<Record<string, unknown>>;
  beliefs: Array<Record<string, unknown>>;
  memories: Array<Record<string, unknown>>;
  causalSeeds: Array<Record<string, unknown>>;
  branches: Array<Record<string, unknown>>;
  modelCalls: Array<Record<string, unknown>>;
}

export interface CreateRunBody {
  userId?: string;
  caseSlug?: string;
  startSceneId?: string;
  startEra?: string;
}

export interface EnterSceneBody {
  userId?: string;
  startEra?: string;
}

export interface CreateBranchBody {
  sourceRunId: string;
  forkEventSequence: number;
  label?: string;
  branchId?: string;
}

export interface BranchDto {
  id: number;
  runId: string;
  branchId: string;
  label: string;
  sourceRunId: string;
  forkEventSequence: number;
  endingId: string | null;
  createdAt: string;
  metadata: Record<string, unknown>;
}

export interface EntitlementDto {
  id: number;
  userId: string;
  scope: string;
  credits: number;
  purchasedAt: string | null;
  expiresAt: string | null;
  metadata: Record<string, unknown>;
}

export interface EntitlementsResponse {
  userId: string;
  entitlements: EntitlementDto[];
  defaultUser: boolean;
}

export interface CatalogResponse {
  products: Product[];
  currency: string;
  version: string;
}

export interface PurchaseMockConfirmBody {
  userId?: string;
  productId: string;
  credits?: number;
  meta?: Record<string, unknown>;
}

export interface PurchaseMockConfirmResponse {
  ok: boolean;
  userId: string;
  productId: string;
  entitlement: EntitlementDto;
  receiptId: string;
}

export interface AnalyticsEventBody {
  userId?: string;
  runId?: string;
  eventName: string;
  payload?: Record<string, unknown>;
  clientVersion?: string;
}

export interface ResumeBody {
  userId?: string;
  targetSceneId?: string;
}

/** POST /v1/runs — 创建新 run */
export async function createRun(body: CreateRunBody = {}): Promise<{ ok: boolean; run: RunDto }> {
  return httpJson("POST", "/v1/runs", body);
}

/** GET /v1/runs/:runId — 读 run 详情 */
export async function getRun(runId: string): Promise<RunDto> {
  return httpJson("GET", `/v1/runs/${encodeURIComponent(runId)}`);
}

/** POST /v1/runs/:runId/scenes/:sceneId/enter — 进入场景 */
export async function enterScene(
  runId: string,
  sceneId: string,
  body: EnterSceneBody = {},
): Promise<{ ok: boolean; runId: string; sceneId: string; scene: SceneMeta; active: Record<string, unknown> }> {
  return httpJson("POST", `/v1/runs/${encodeURIComponent(runId)}/scenes/${encodeURIComponent(sceneId)}/enter`, body);
}

/** POST /v1/runs/:runId/resume — 续玩 */
export async function resumeRun(
  runId: string,
  body: ResumeBody = {},
): Promise<{ ok: boolean; runId: string; active: Record<string, unknown> }> {
  return httpJson("POST", `/v1/runs/${encodeURIComponent(runId)}/resume`, body);
}

/** POST /v1/runs/:runId/actions — 核心写端点 */
export async function submitActionReal(
  body: ActionRequestBody,
): Promise<ActionResponseBody> {
  return httpJson("POST", `/v1/runs/${encodeURIComponent(body.runId)}/actions`, body);
}

/** GET /v1/runs/:runId/timeline — 时间线 */
export async function getTimeline(runId: string): Promise<TimelineResponse> {
  return httpJson("GET", `/v1/runs/${encodeURIComponent(runId)}/timeline`);
}

/** GET /v1/runs/:runId/archive — 档案馆 */
export async function getArchive(runId: string): Promise<ArchiveResponse> {
  return httpJson("GET", `/v1/runs/${encodeURIComponent(runId)}/archive`);
}

/** POST /v1/runs/:runId/branches — 创建重演分支 */
export async function createBranch(
  runId: string,
  body: CreateBranchBody,
): Promise<{ ok: boolean; branch: BranchDto }> {
  return httpJson("POST", `/v1/runs/${encodeURIComponent(runId)}/branches`, body);
}

/** GET /v1/runs/:runId/branches — 列分支 */
export async function listBranches(runId: string): Promise<{ runId: string; count: number; branches: BranchDto[] }> {
  return httpJson("GET", `/v1/runs/${encodeURIComponent(runId)}/branches`);
}

/** GET /v1/catalog — 商品目录 */
export async function getCatalog(): Promise<CatalogResponse> {
  return httpJson("GET", "/v1/catalog");
}

/** GET /v1/entitlements — 用户权益 */
export async function getEntitlements(userId: string = "demo-user"): Promise<EntitlementsResponse> {
  return httpJson("GET", `/v1/entitlements?userId=${encodeURIComponent(userId)}`);
}

/** POST /v1/purchases/mock-confirm — 模拟购买 */
export async function purchaseMockConfirm(
  body: PurchaseMockConfirmBody,
): Promise<PurchaseMockConfirmResponse> {
  return httpJson("POST", "/v1/purchases/mock-confirm", body);
}

/** POST /v1/analytics/events — 埋点 */
export async function recordAnalytics(
  body: AnalyticsEventBody,
): Promise<{ ok: boolean; event: Record<string, unknown> }> {
  return httpJson("POST", "/v1/analytics/events", body);
}

/** GET /v1/scenes/:sceneId — 场景元数据 */
export async function fetchSceneMetaReal(sceneId: SceneId): Promise<SceneMeta> {
  return httpJson("GET", `/v1/scenes/${encodeURIComponent(sceneId)}`);
}

// =============================================================================
// REST：取场景元数据
// =============================================================================

export async function fetchSceneMeta(sceneId: string): Promise<SceneMeta> {
  const r = await fetch(`${API_BASE}/scenes/${sceneId}`, {
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!r.ok) throw new Error(`fetchSceneMeta ${sceneId}: ${r.status}`);
  return (await r.json()) as SceneMeta;
}

export async function fetchSnapshot(runId: string): Promise<WorldSnapshot> {
  const response = await httpJson<{ runId: string; snapshot: WorldSnapshot; source: string }>(
    "GET", `/v1/runs/${encodeURIComponent(runId)}/snapshot`,
  );
  return response.snapshot;
}

// =============================================================================
// 流式回合：POST /turns → SSE
// =============================================================================

export interface StreamTurnHandlers {
  onNpcPartial?: (text: string) => void;
  onNpcFinal?: (text: string, intent: string) => void;
  onResolver?: (outcome: ResolverOutcome) => void;
  onDegraded?: (level: DegradationLevel) => void;
  onError?: (e: Error, level: DegradationLevel) => void;
  onDone?: () => void;
}

export interface TurnOptions {
  runId: string;
  sceneId: string;
  actionType: ActionType;
  actorId: string;
  targetId?: string | null;
  evidenceIds?: string[];
  utterance?: string;
  tone?: Tone;
  disclosureLevel?: number;
  isDeceptive?: boolean;
}

/**
 * 提交玩家动作；服务端走 Director + NPC + Resolver 三段
 * 单回合最多 2 次 LLM 调用（决策 5）
 */
export async function submitTurn(
  opts: TurnOptions,
  handlers: StreamTurnHandlers = {},
): Promise<TurnResponse> {
  const started = performance.now();
  const clientActionId = uuid();
  const eventSequence = useStore.getState().lastEventSequence + 1;

  const action: PlayerAction = {
    runId: opts.runId,
    sceneId: opts.sceneId,
    clientActionId,
    expectedEventSequence: eventSequence,
    actionType: opts.actionType,
    actorId: opts.actorId,
    targetId: opts.targetId ?? null,
    evidenceIds: opts.evidenceIds ?? [],
    utterance: (opts.utterance ?? "").slice(0, 500),
    tone: opts.tone ?? "neutral",
    disclosureLevel: Math.max(0, Math.min(1, opts.disclosureLevel ?? 0.5)),
    isDeceptive: opts.isDeceptive ?? false,
    clientTimestamp: new Date().toISOString(),
    schemaVersion: "1.0.0",
  };

  useStore.getState().setPendingAction({ clientActionId, actionType: opts.actionType });
  useStore.getState().setNetworkState("connecting");

  // ---- 软超时：L1 NPC 反应兜底
  let l1Triggered = false;
  const l1Timer = window.setTimeout(() => {
    l1Triggered = true;
    useStore.getState().setDegradation("L1");
    handlers.onNpcPartial?.(pickFallback());
    handlers.onDegraded?.("L1");
  }, FAST_TIMEOUT_MS);

  // ---- 硬超时：整回合兜底 L3
  const ac = new AbortController();
  const hardTimer = window.setTimeout(() => ac.abort(), TIMEOUT_MS);

  try {
    const r = await fetch(`${API_BASE}/turns`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(action),
      signal: ac.signal,
    });

    if (!r.ok || !r.body) {
      throw new Error(`submitTurn HTTP ${r.status}`);
    }

    useStore.getState().setNetworkState("streaming");

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let lastOutcome: ResolverOutcome | null = null;
    let lastDegradation: DegradationLevel = l1Triggered ? "L1" : "none";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE: 解析 event / data
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const evt = parseSseBlock(raw);
        if (!evt) continue;
        if (evt.event === "npc_partial") {
          window.clearTimeout(l1Timer);
          handlers.onNpcPartial?.(String(evt.data?.text ?? ""));
        } else if (evt.event === "npc_final") {
          handlers.onNpcFinal?.(String(evt.data?.text ?? ""), String(evt.data?.intent ?? ""));
        } else if (evt.event === "director") {
          // Director 不直接送 UI
        } else if (evt.event === "resolver") {
          lastOutcome = evt.data as unknown as ResolverOutcome;
          handlers.onResolver?.(lastOutcome);
        } else if (evt.event === "degraded") {
          lastDegradation = (evt.data?.level as DegradationLevel) ?? lastDegradation;
          useStore.getState().setDegradation(lastDegradation);
          handlers.onDegraded?.(lastDegradation);
        } else if (evt.event === "error") {
          const e = new Error(String(evt.data?.message ?? "server error"));
          useStore.getState().recordError(e.message);
          handlers.onError?.(e, lastDegradation);
        } else if (evt.event === "done") {
          // exit
        }
      }
    }

    window.clearTimeout(l1Timer);
    window.clearTimeout(hardTimer);

    const latency = performance.now() - started;
    useStore.getState().recordLatency(latency);

    if (!lastOutcome) {
      // L3 兜底：服务端没给 ResolverOutcome 时，本地构造一个最低骨架
      useStore.getState().setDegradation("L3");
      const fb = pickFallback();
      lastOutcome = localFallbackOutcome(action, fb);
      handlers.onDegraded?.("L3");
    }

    if (latency > P95_BUDGET_MS) {
      useStore.getState().setDegradation("L2");
      handlers.onDegraded?.("L2");
    }

    useStore.getState().appendOutcome(lastOutcome);
    useStore.getState().bumpTurn();
    useStore.getState().setNetworkState("idle");
    useStore.getState().setPendingAction(null);

    handlers.onDone?.();

    return {
      outcome: lastOutcome,
      clientActionId,
      degraded: lastDegradation,
      fallbackUsed: lastDegradation !== "none",
      latencyMs: Math.round(latency),
      resolvedText: lastOutcome.acceptedNpcAction.resolvedText,
    };
  } catch (e) {
    window.clearTimeout(l1Timer);
    window.clearTimeout(hardTimer);
    const err = e as Error;
    useStore.getState().recordError(err.message);

    // L4：网络/超时
    useStore.getState().setDegradation("L4");
    const fb = pickFallback();
    const fallback = localFallbackOutcome(action, fb);
    useStore.getState().appendOutcome(fallback);
    useStore.getState().setPendingAction(null);
    useStore.getState().setNetworkState("error");
    handlers.onError?.(err, "L4");
    handlers.onDegraded?.("L4");
    handlers.onDone?.();

    return {
      outcome: fallback,
      clientActionId,
      degraded: "L4",
      fallbackUsed: true,
      latencyMs: Math.round(performance.now() - started),
      resolvedText: fallback.acceptedNpcAction.resolvedText,
    };
  }
}

// =============================================================================
// SSE 解析
// =============================================================================

interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

function parseSseBlock(block: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  const dataStr = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(dataStr) };
  } catch {
    return { event, data: { text: dataStr } };
  }
}

// =============================================================================
// 本地兜底（mock / L3 降级）
// =============================================================================

function localFallbackOutcome(action: PlayerAction, fallbackText: string): ResolverOutcome {
  const eventSequence = action.expectedEventSequence;
  return {
    outcomeId: uuid(),
    runId: action.runId,
    eventSequence,
    triggerPlayerActionId: action.clientActionId,
    triggerDirectorProposalId: null,
    idempotencyKey: `${action.runId}:${eventSequence}:${action.clientActionId}`,
    acceptedNpcAction: {
      proposalId: uuid(),
      characterId: action.targetId ?? "npc_default",
      proposedAction: "silence",
      speechIntent: "remain_silent",
      resolvedText: fallbackText,
    },
    rejectedNpcActions: [],
    relationshipDelta: [],
    beliefUpdates: [],
    artifactUpdates: [],
    newCausalSeeds: [],
    firedCausalSeeds: [],
    nextBeat: {
      sceneId: action.sceneId,
      beatId: "fallback_beat",
      transition: "continue",
      legalEndingId: null,
    },
    clampedValues: [],
    auditTrail: { llmCalls: [], deterministicDecisions: ["fallback_L3_or_L4"] },
    timestamp: new Date().toISOString(),
    schemaVersion: "1.0.0",
  };
}

// =============================================================================
// 客户端 mock（无服务端时降级到内置脚本）
// =============================================================================

const MOCK_NPC_LINES: Array<{ intent: string; text: string }> = [
  { intent: "deflect", text: "（他没有立刻回答，只是把那张照片的边角压平了。）" },
  { intent: "admit", text: "（他抬起头。灯光把他的脸切成两半。）" },
  { intent: "question", text: "（他/她想问什么，但最后只是笑了一下。）" },
  { intent: "comfort", text: "（一段沉默。远处地铁的震动把灯泡晃了一下。）" },
  { intent: "reveal_truth", text: "（他/她的声音比想象中更轻——像是在念一张没署名的字条。）" },
  { intent: "remain_silent", text: "（电影在放映。他/她的眼睛在银幕上，不在你身上。）" },
];

export async function mockSubmitTurn(action: PlayerAction): Promise<TurnResponse> {
  const started = performance.now();
  await new Promise((r) => setTimeout(r, 280 + Math.random() * 540));
  const pick = MOCK_NPC_LINES[Math.floor(Math.random() * MOCK_NPC_LINES.length)];

  const outcome: ResolverOutcome = {
    ...localFallbackOutcome(action, pick.text),
    acceptedNpcAction: {
      ...localFallbackOutcome(action, pick.text).acceptedNpcAction,
      speechIntent: pick.intent as ResolverOutcome["acceptedNpcAction"]["speechIntent"],
      resolvedText: pick.text,
    },
  };
  useStore.getState().appendOutcome(outcome);
  useStore.getState().bumpTurn();
  const latency = performance.now() - started;
  useStore.getState().recordLatency(latency);
  return {
    outcome,
    clientActionId: action.clientActionId,
    degraded: latency > P95_BUDGET_MS ? "L2" : "none",
    fallbackUsed: false,
    latencyMs: Math.round(latency),
    resolvedText: pick.text,
  };
}

// =============================================================================
// 模式切换：VITE_USE_MOCK=false 时走真实服务端
// -----------------------------------------------------------------------------
// 这一段是 useSceneRunner 的主入口。
//   submitAction(PlayerAction)  ← 客户端 hook 唯一调用
//     ├─ USE_MOCK=true  → mockSubmitTurn
//     └─ USE_MOCK=false → submitActionReal (FastAPI /v1/runs/:id/actions)
// =============================================================================

/**
 * Submit a player action — switchable between mock and real
 * server.  Used by :func:`useSceneRunner` and any other client
 * code that needs to advance the run.
 *
 * The shape returned is :class:`TurnResponse`, regardless of
 * which path ran — the UI never has to branch.
 */
export async function submitAction(
  action: PlayerAction,
  options: { clientVersion?: string } = {},
): Promise<TurnResponse> {
  const store = useStore.getState();
  if (store.pendingAction) {
    throw new Error(`action already pending: ${store.pendingAction.clientActionId}`);
  }
  store.setPendingAction({ clientActionId: action.clientActionId, actionType: action.actionType });
  try {
    if (USE_MOCK) return await mockSubmitTurn(action);
    return await submitActionViaServer(action, options);
  } finally {
    if (useStore.getState().pendingAction?.clientActionId === action.clientActionId) {
      useStore.getState().setPendingAction(null);
    }
  }
}

async function submitActionViaServer(
  action: PlayerAction,
  options: { clientVersion?: string },
): Promise<TurnResponse> {
  const started = performance.now();
  useStore.getState().setNetworkState("connecting");

  try {
    const resp = await submitActionReal({
      runId: action.runId,
      sceneId: action.sceneId,
      clientActionId: action.clientActionId,
      expectedEventSequence: action.expectedEventSequence,
      playerAction: action,
      clientVersion: options.clientVersion,
    });

    const latency = (resp.latencyMs) || Math.round(performance.now() - started);
    useStore.getState().recordLatency(latency);
    const outcome = resp.outcome as ResolverOutcome;
    useStore.getState().applyServerTurn(resp.snapshot, outcome, resp.eventSequence);
    useStore.getState().setDegradation((resp.degraded as DegradationLevel) || "none");
    useStore.getState().setNetworkState("idle");

    if (resp.degradedToL3 || resp.degraded === "L3") {
      // 决策 5：L3 提示
      useStore.getState().setDegradation("L3");
    }

    return {
      outcome,
      npcProposals: [],
      clientActionId: action.clientActionId,
      degraded: (resp.degraded as DegradationLevel) || "none",
      fallbackUsed: resp.fallbackUsed,
      latencyMs: latency,
      resolvedText: resp.resolvedText || outcome.acceptedNpcAction.resolvedText,
    };
  } catch (e) {
    const err = e as Error;
    useStore.getState().recordError(err.message);
    useStore.getState().setDegradation("L4");
    useStore.getState().setNetworkState("error");
    // Transport/HTTP failure is not a persisted game turn. Never forge success.
    throw err;
  }
}

// =============================================================================
// Helper: 用法示意
// =============================================================================

/**
 * 简单用法（mock 模式，不连服务端）：
 *
 *   const result = await mockSubmitTurn(action);
 *   setNarration(result.resolvedText, true);
 */
