// =============================================================================
// 革命街没有尽头 · Zustand 状态管理
// -----------------------------------------------------------------------------
// 客户端缓存（不保存权威状态）。所有权威状态在服务端 Resolver。
// 决策 5 强制：单回合模型调用 ≤ 2 次；4 级降级链必须有视觉反馈。
// =============================================================================

import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import type {
  ActionType,
  CausalSeed,
  DegradationLevel,
  InvestigatableObject,
  Phase,
  ProductId,
  ResolverOutcome,
  RunState,
  SceneId,
  SceneMeta,
  Tone,
  WorldSnapshot,
} from "@/types/schemas";

// -----------------------------------------------------------------------------
// 运行（run）状态
// -----------------------------------------------------------------------------
export interface RunSlice {
  runId: string | null;
  sceneId: SceneId | null;
  currentState: RunState;
  worldSnapshot: WorldSnapshot | null;
  recentOutcomes: ResolverOutcome[];
  causalSeedsActive: CausalSeed[];
  turnIndex: number;
  globalTension: number;
  // 客户端缓存的事件序号（用于幂等）
  lastEventSequence: number;
  // 待发送的提案（防双击）
  pendingAction: { clientActionId: string; actionType: ActionType } | null;

  setRun: (runId: string, sceneId: SceneId) => void;
  setState: (state: RunState) => void;
  setSnapshot: (snapshot: WorldSnapshot) => void;
  appendOutcome: (outcome: ResolverOutcome) => void;
  bumpTurn: () => void;
  setPendingAction: (pa: { clientActionId: string; actionType: ActionType } | null) => void;
  reset: () => void;
}

// -----------------------------------------------------------------------------
// 场景内行为进度
// -----------------------------------------------------------------------------
export interface SceneProgress {
  investigated: string[];        // 已调查对象 ID
  turnsByAction: Partial<Record<ActionType, number>>;
  evidenceCollected: string[];   // 已发现证据 ID
  causalSeedsFired: string[];    // 本场景已触发的种子
  artifactsHeld: string[];       // 当前持有的物件
  npcReactions: Array<{
    characterId: string;
    text: string;
    intent: string;
    timestamp: string;
  }>;
}

export interface SceneSlice {
  sceneMeta: SceneMeta | null;
  sceneProgress: SceneProgress;
  currentNarration: string;       // 当前旁白文本（"你看到了 X"）
  typewriterActive: boolean;
  loadScene: (meta: SceneMeta) => void;
  markInvestigated: (id: string) => void;
  spendAction: (type: ActionType) => void;
  addEvidence: (evidenceId: string) => void;
  fireSeed: (seedId: string) => void;
  holdArtifact: (id: string) => void;
  pushNpcReaction: (r: SceneProgress["npcReactions"][number]) => void;
  setNarration: (text: string, typewriter?: boolean) => void;
  clearScene: () => void;
}

// -----------------------------------------------------------------------------
// 旁观者 / 视角（决策 2：默认 = 第三人称旁观者）
// -----------------------------------------------------------------------------
export type POVMode =
  | "observer"
  | "leila"
  | "arash"
  | "kamran"
  | "maryam"
  // W12: case_02 人物
  | "natasha_roschina"
  | "ilya_berman"
  | "sasha_kuzmin"
  | "lisa_hoffmann";

export interface ObserverSlice {
  povMode: POVMode;
  unlockedPOVs: POVMode[];
  // 决策 2：付费解锁的视角
  setPOV: (pov: POVMode) => void;
  unlockPOV: (pov: POVMode) => void;
}

// -----------------------------------------------------------------------------
// 付费 / 商业化（决策 4）
// -----------------------------------------------------------------------------
export interface CommerceSlice {
  ownedProducts: ProductId[];
  credits: number;                // 主调用积分
  replayTickets: number;          // 平行演算次数
  paywallOpen: boolean;
  paywallFrom: SceneId | RunState | null;
  setCredits: (c: number) => void;
  spendCredits: (n: number) => boolean;
  grantProduct: (id: ProductId, credits?: number, replays?: number) => void;
  consumeReplay: () => boolean;
  openPaywall: (from: SceneId | RunState) => void;
  closePaywall: () => void;
}

// -----------------------------------------------------------------------------
// API 通信 / 降级（决策 5）
// -----------------------------------------------------------------------------
export type NetworkState = "idle" | "connecting" | "streaming" | "degraded" | "error";

export interface ApiSlice {
  networkState: NetworkState;
  degradationLevel: DegradationLevel;
  lastError: string | null;
  // P95 监控（决策 5：关键交互 P95 < 4s）
  recentLatencyMs: number[];

  setNetworkState: (s: NetworkState) => void;
  setDegradation: (d: DegradationLevel) => void;
  recordError: (e: string) => void;
  recordLatency: (ms: number) => void;
}

// -----------------------------------------------------------------------------
// 设置 / 偏好
// -----------------------------------------------------------------------------
export interface SettingsSlice {
  audioEnabled: boolean;          // 默认静音，用户手势启动
  audioVolume: number;            // 0-1
  textSpeed: "slow" | "normal" | "fast";
  reducedMotion: boolean;
  language: "zh-CN" | "en";
  setAudio: (enabled: boolean) => void;
  setVolume: (v: number) => void;
  setTextSpeed: (s: "slow" | "normal" | "fast") => void;
  setReducedMotion: (b: boolean) => void;
  setLanguage: (l: "zh-CN" | "en") => void;
}

// -----------------------------------------------------------------------------
// 完整 store
// -----------------------------------------------------------------------------
export type Store = RunSlice & SceneSlice & ObserverSlice & CommerceSlice & ApiSlice & SettingsSlice;

const initialSceneProgress: SceneProgress = {
  investigated: [],
  turnsByAction: {},
  evidenceCollected: [],
  causalSeedsFired: [],
  artifactsHeld: [],
  npcReactions: [],
};

const MAX_LATENCY_SAMPLES = 20;
const MAX_RECENT_OUTCOMES = 32;

export const useStore = create<Store>()(
  subscribeWithSelector((set, get) => ({
    // --- Run ---
    runId: null,
    sceneId: null,
    currentState: "idle",
    worldSnapshot: null,
    recentOutcomes: [],
    causalSeedsActive: [],
    turnIndex: 0,
    globalTension: 0.1,
    lastEventSequence: 0,
    pendingAction: null,

    setRun: (runId, sceneId) => set({ runId, sceneId, currentState: "scene_active" }),
    setState: (state) => set({ currentState: state }),
    setSnapshot: (snapshot) =>
      set({
        worldSnapshot: snapshot,
        lastEventSequence: snapshot.eventSequence,
        globalTension: snapshot.canonicalState.globalTension,
        turnIndex: snapshot.canonicalState.turnIndex,
        causalSeedsActive: snapshot.causalSeedsActive,
      }),
    appendOutcome: (outcome) =>
      set((s) => ({
        recentOutcomes: [outcome, ...s.recentOutcomes].slice(0, MAX_RECENT_OUTCOMES),
        lastEventSequence: outcome.eventSequence,
      })),
    bumpTurn: () => set((s) => ({ turnIndex: s.turnIndex + 1 })),
    setPendingAction: (pa) => set({ pendingAction: pa }),
    reset: () =>
      set({
        runId: null,
        sceneId: null,
        currentState: "idle",
        worldSnapshot: null,
        recentOutcomes: [],
        causalSeedsActive: [],
        turnIndex: 0,
        globalTension: 0.1,
        lastEventSequence: 0,
        pendingAction: null,
      }),

    // --- Scene ---
    sceneMeta: null,
    sceneProgress: initialSceneProgress,
    currentNarration: "",
    typewriterActive: false,

    loadScene: (meta) =>
      set({
        sceneMeta: meta,
        sceneProgress: { ...initialSceneProgress, npcReactions: [] },
        currentNarration: "",
        typewriterActive: false,
      }),
    markInvestigated: (id) =>
      set((s) =>
        s.sceneProgress.investigated.includes(id)
          ? s
          : { sceneProgress: { ...s.sceneProgress, investigated: [...s.sceneProgress.investigated, id] } },
      ),
    spendAction: (type) =>
      set((s) => ({
        sceneProgress: {
          ...s.sceneProgress,
          turnsByAction: { ...s.sceneProgress.turnsByAction, [type]: (s.sceneProgress.turnsByAction[type] ?? 0) + 1 },
        },
      })),
    addEvidence: (evidenceId) =>
      set((s) => ({
        sceneProgress: {
          ...s.sceneProgress,
          evidenceCollected: s.sceneProgress.evidenceCollected.includes(evidenceId)
            ? s.sceneProgress.evidenceCollected
            : [...s.sceneProgress.evidenceCollected, evidenceId],
        },
      })),
    fireSeed: (seedId) =>
      set((s) => ({
        sceneProgress: {
          ...s.sceneProgress,
          causalSeedsFired: s.sceneProgress.causalSeedsFired.includes(seedId)
            ? s.sceneProgress.causalSeedsFired
            : [...s.sceneProgress.causalSeedsFired, seedId],
        },
      })),
    holdArtifact: (id) =>
      set((s) => ({
        sceneProgress: {
          ...s.sceneProgress,
          artifactsHeld: s.sceneProgress.artifactsHeld.includes(id)
            ? s.sceneProgress.artifactsHeld
            : [...s.sceneProgress.artifactsHeld, id],
        },
      })),
    pushNpcReaction: (r) =>
      set((s) => ({
        sceneProgress: {
          ...s.sceneProgress,
          npcReactions: [...s.sceneProgress.npcReactions, r].slice(-16),
        },
      })),
    setNarration: (text, typewriter = false) =>
      set({ currentNarration: text, typewriterActive: typewriter }),
    clearScene: () => set({ sceneMeta: null, sceneProgress: initialSceneProgress }),

    // --- Observer / POV ---
    povMode: "observer",
    unlockedPOVs: [],
    setPOV: (pov) => {
      const { unlockedPOVs, povMode } = get();
      // 决策 2：默认旁观者；切换视角需要先解锁
      if (pov !== "observer" && !unlockedPOVs.includes(pov)) {
        // 弹付费墙
        useStore.getState().openPaywall("pov_unlock" as unknown as SceneId);
        return;
      }
      if (pov === povMode) return;
      set({ povMode: pov });
    },
    unlockPOV: (pov) =>
      set((s) => ({
        unlockedPOVs: s.unlockedPOVs.includes(pov) ? s.unlockedPOVs : [...s.unlockedPOVs, pov],
      })),

    // --- Commerce ---
    ownedProducts: ["free_sample"],
    credits: 30,                  // 免费样章给 30 积分
    replayTickets: 1,             // 免费样章给 1 次重演
    paywallOpen: false,
    paywallFrom: null,

    setCredits: (c) => set({ credits: Math.max(0, c) }),
    spendCredits: (n) => {
      const { credits } = get();
      if (credits < n) return false;
      set({ credits: credits - n });
      return true;
    },
    grantProduct: (id, credits = 0, replays = 0) =>
      set((s) => ({
        ownedProducts: s.ownedProducts.includes(id) ? s.ownedProducts : [...s.ownedProducts, id],
        credits: s.credits + credits,
        replayTickets: s.replayTickets + replays,
      })),
    consumeReplay: () => {
      const { replayTickets } = get();
      if (replayTickets <= 0) return false;
      set({ replayTickets: replayTickets - 1 });
      return true;
    },
    openPaywall: (from) => set({ paywallOpen: true, paywallFrom: from }),
    closePaywall: () => set({ paywallOpen: false, paywallFrom: null }),

    // --- API ---
    networkState: "idle",
    degradationLevel: "none",
    lastError: null,
    recentLatencyMs: [],

    setNetworkState: (s) => set({ networkState: s }),
    setDegradation: (d) => set({ degradationLevel: d }),
    recordError: (e) => set({ lastError: e, networkState: "error" }),
    recordLatency: (ms) =>
      set((s) => ({
        recentLatencyMs: [...s.recentLatencyMs, ms].slice(-MAX_LATENCY_SAMPLES),
      })),

    // --- Settings ---
    audioEnabled: false,           // 默认静音
    audioVolume: 0.6,
    textSpeed: "normal",
    reducedMotion: false,
    language: "zh-CN",

    setAudio: (enabled) => set({ audioEnabled: enabled }),
    setVolume: (v) => set({ audioVolume: Math.max(0, Math.min(1, v)) }),
    setTextSpeed: (s) => set({ textSpeed: s }),
    setReducedMotion: (b) => set({ reducedMotion: b }),
    setLanguage: (l) => set({ language: l }),
  })),
);

// =============================================================================
// Selectors / helpers
// =============================================================================

/** P95 延迟（决策 5：< 4000ms） */
export function getP95Latency(): number {
  const samples = useStore.getState().recentLatencyMs;
  if (samples.length === 0) return 0;
  const sorted = [...samples].sort((a, b) => a - b);
  const idx = Math.floor(sorted.length * 0.95);
  return sorted[Math.min(idx, sorted.length - 1)];
}

/** 当前场景的可调查对象 */
export function getInvestigatableObjects(): InvestigatableObject[] {
  return useStore.getState().sceneMeta?.investigatableObjects ?? [];
}

/** 决策 4 商业化档位（每个付费点的"availableFromState"约束） */
export const PRODUCT_TRIGGER_STATES: Record<ProductId, RunState[]> = {
  free_sample: ["idle"],
  passport: ["scene_ended", "act_ended", "run_ended"],
  collectors: ["act_ended", "run_ended"],
  parallel_ops: ["scene_ended", "act_ended", "run_ended"],
  credits: ["scene_ended", "act_ended", "run_ended"],
  pov_unlock: ["scene_ended", "act_ended", "run_ended", "unlocked"],
  keepsake: ["run_ended"],
};

/** 决策红线：场景中段绝不能弹付费墙 */
export function canOpenPaywallInState(state: RunState): boolean {
  return state === "scene_ended" || state === "act_ended" || state === "run_ended" || state === "unlocked";
}

// 阶段判定（基于 phase）
export function deriveRunState(snapshot: WorldSnapshot | null): RunState {
  if (!snapshot) return "idle";
  const phase: Phase = snapshot.canonicalState.phase;
  if (phase === "ended") return snapshot.canonicalState.endingId ? "run_ended" : "scene_ended";
  return "scene_active";
}
