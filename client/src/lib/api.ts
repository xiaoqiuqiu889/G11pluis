// =============================================================================
// 革命街没有尽头 · API 客户端
// -----------------------------------------------------------------------------
// 与 FastAPI 服务端通信：流式响应（SSE / EventSource）+ REST
// 决策 5：单回合模型调用 ≤ 2 次；P95 < 4s；4 级降级链必须有视觉反馈。
// =============================================================================

import type {
  ActionType,
  DegradationLevel,
  InvestigatableObject,
  NpcProposal,
  PlayerAction,
  ResolverOutcome,
  SceneMeta,
  Tone,
  WorldSnapshot,
} from "@/types/schemas";
import { useStore } from "./store";

// -----------------------------------------------------------------------------
// 配置
// -----------------------------------------------------------------------------
const API_BASE: string =
  (typeof import.meta !== "undefined" && (import.meta as { env?: Record<string, string> }).env?.VITE_API_BASE) ||
  (typeof window !== "undefined" && (window as unknown as { __API_BASE__?: string }).__API_BASE__) ||
  "http://localhost:8000";

const TIMEOUT_MS = 8_000;                 // 决策 5：客户端侧兜底
const FAST_TIMEOUT_MS = 1_500;            // L1 软超时（NPC 反应兜底）
const P95_BUDGET_MS = 4_000;              // 决策 5 红线

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
  const r = await fetch(`${API_BASE}/runs/${runId}/snapshot`, {
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!r.ok) throw new Error(`fetchSnapshot ${runId}: ${r.status}`);
  return (await r.json()) as WorldSnapshot;
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
// Helper: 用法示意
// =============================================================================

/**
 * 简单用法（mock 模式，不连服务端）：
 *
 *   const result = await mockSubmitTurn(action);
 *   setNarration(result.resolvedText, true);
 */
