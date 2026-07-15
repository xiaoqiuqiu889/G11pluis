// =============================================================================
// 革命街没有尽头 · 共享场景 Hook
// -----------------------------------------------------------------------------
// - 加载 SceneMeta
// - 真后端模式 (VITE_USE_MOCK=false)：先 POST /v1/runs 拿到 server runId
//   再让玩家交互；mock 模式用本地 UUID（mock 不校验 runId）
// - 提交动作（mock 模式 / 真服务端）
// - 处理转场、付费墙触发、降级
//
// 历史 bug 修复：W12-E2E-runsync
//   旧版 setRun(crypto.randomUUID()) 是假创建 — 后端 registry 从未见过该 UUID
//   导致 /v1/runs/{id}/actions 永远 404 "run not found"
// ============================================================================

import { useEffect, useRef, useState } from "react";
import { useStore } from "@/lib/store";
import { SCENE_MOCKS } from "@/mocks/scenes";
import { createRun, enterScene, fetchSnapshot, submitAction, USE_MOCK, uuid as makeUuid } from "@/lib/api";
import type { ActionType, SceneId, SceneMeta, Tone } from "@/types/schemas";
import { audioEngine } from "@/audio/AudioEngine";

export interface UseSceneRunnerOptions {
  sceneId: keyof typeof SCENE_MOCKS;
  actorId?: string;
  targetId?: string;
  artBackground?: string;
  audioChapter?: string;
}

export interface UseSceneRunnerResult {
  sceneMeta: SceneMeta | null;
  /** 场景 meta + runId 都已就绪，可安全提交动作 */
  ready: boolean;
  /** 后端 run 创建阶段失败（仅 VITE_USE_MOCK=false 时发生） */
  runError: string | null;
  /** 触发 run 创建重试（清空 runId 并重新 createRun） */
  retryRun: () => void;
  error: string | null;
  handleAction: (params: {
    actionType: ActionType;
    utterance: string;
    tone: Tone;
    targetId?: string | null;
    evidenceIds?: string[];
  }) => Promise<void>;
  finishScene: (endingId: string) => void;
}

export function useSceneRunner(opts: UseSceneRunnerOptions): UseSceneRunnerResult {
  const { sceneId, actorId = "leila", targetId, audioChapter } = opts;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const sceneMeta = useStore((s) => s.sceneMeta);
  const loadScene = useStore((s) => s.loadScene);
  const markInvestigated = useStore((s) => s.markInvestigated);
  const spendAction = useStore((s) => s.spendAction);
  const refundAction = useStore((s) => s.refundAction);
  const pushNpcReaction = useStore((s) => s.pushNpcReaction);
  const setNarration = useStore((s) => s.setNarration);
  const setRun = useStore((s) => s.setRun);
  const setState = useStore((s) => s.setState);
  const spendCredits = useStore((s) => s.spendCredits);
  const refundCredits = useStore((s) => s.refundCredits);

  const openPaywall = useStore((s) => s.openPaywall);
  const audioEnabled = useStore((s) => s.audioEnabled);
  const runId = useStore((s) => s.runId);

  // 防止 React 18 strict mode 双调
  const initStarted = useRef(false);

  // 加载场景 meta + （真后端模式）注册 run
  useEffect(() => {
    if (initStarted.current) return;
    initStarted.current = true;

    const meta = SCENE_MOCKS[sceneId];
    if (!meta) {
      setError(`未找到场景 ${sceneId}`);
      setLoading(false);
      return;
    }
    loadScene(meta);
    if (audioEnabled && audioChapter) {
      void audioEngine.start(audioChapter);
    }
    // 初始旁白
    setNarration(initialNarration(sceneId), true);

    // 真后端模式：必须先 POST /v1/runs 拿到 runId
    if (USE_MOCK) {
      const localId = `mock-${crypto.randomUUID()}`;
      setRun(localId, sceneId as SceneId);
      setLoading(false);
    } else {
      void ensureServerRun(sceneId, meta.caseSlug);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneId]);

  // 调用后端 createRun
  async function ensureServerRun(
    sid: keyof typeof SCENE_MOCKS,
    caseSlug: string | undefined,
  ): Promise<void> {
    setRunError(null);
    useStore.getState().setNetworkState("connecting");
    try {
      const resp = await createRun({
        caseSlug: caseSlug ?? "case_01_revolution_street",
        startSceneId: sid,
        startEra: SCENE_MOCKS[sid].era,
      });
      const serverRunId = resp.run?.runId;
      if (!serverRunId) {
        throw new Error("服务端 createRun 未返回 runId");
      }
      // 进入场景（让后端 snapshot 初始化为该场景）
      const entered = await enterScene(serverRunId, sid, { startEra: SCENE_MOCKS[sid].era });
      const snapshot = await fetchSnapshot(serverRunId);
      setRun(serverRunId, sid as SceneId);
        // enterScene 失败不应阻塞 runId — 玩家至少可以试
        // eslint-disable-next-line no-console
      useStore.getState().setSnapshot(snapshot);
      loadScene(entered.scene);
      // A successful retry must clear the stale service-unavailable state
      // left by an earlier create/enter/snapshot failure.
      useStore.getState().setDegradation("none");
      useStore.getState().setNetworkState("idle");
      setLoading(false);
    } catch (e) {
      const err = e as Error;
      useStore.getState().recordError(err.message);
      useStore.getState().setDegradation("L4");
      useStore.getState().setNetworkState("error");
      setRunError(`无法创建 run: ${err.message}。请检查后端是否启动，或切回 mock 模式。`);
      setLoading(false);
    }
  }

  const retryRun = () => {
    const meta = SCENE_MOCKS[sceneId];
    if (!meta) return;
    initStarted.current = false;
    setLoading(true);
    setRunError(null);
    void ensureServerRun(sceneId, meta.caseSlug);
  };

  // 动作：检查积分、检查预算、提交
  const handleAction: UseSceneRunnerResult["handleAction"] = async (params) => {
    const stateAtSubmit = useStore.getState();
    const activeRunId = stateAtSubmit.runId;

    if (loading || runError || !activeRunId || stateAtSubmit.sceneId !== sceneId) {
      // runId 还没就绪，告知用户
      setNarration("（场景还没准备好……请稍等或刷新页面。）", true);
      return;
    }
    if (stateAtSubmit.pendingAction) {
      return;
    }
    // 积分检查（决策 4：免费样章 30 积分，1 主调用 = 1 积分）
    if (stateAtSubmit.credits <= 0) {
      openPaywall(sceneId as SceneId);
      return;
    }
    // 预算检查
    const budget = sceneMeta?.turnBudget[params.actionType] ?? 0;
    const used = useStore.getState().sceneProgress.turnsByAction[params.actionType] ?? 0;
    if (budget > 0 && used >= budget) {
      setNarration(`（这一场里，你能做这件事的次数用完了。镜头会停一下。）`, true);
      return;
    }
    spendAction(params.actionType);
    spendCredits(1);

    // 提交（VITE_USE_MOCK=true → 内置 mock；false → 真服务端）
    let result;
    try {
      result = await submitAction({
        runId: activeRunId,
        sceneId,
        clientActionId: makeUuid(),
        expectedEventSequence: stateAtSubmit.lastEventSequence,
        actionType: params.actionType,
        actorId,
        targetId: params.targetId ?? targetId ?? null,
        evidenceIds: params.evidenceIds ?? [],
        utterance: params.utterance,
        tone: params.tone,
        disclosureLevel: 0.5,
        isDeceptive: false,
        clientTimestamp: new Date().toISOString(),
        schemaVersion: "1.0.0",
      }, { clientVersion: "1.0.0" });
    } catch (e) {
      const err = e as Error;
      // 不抛 — 把错误以旁白形式呈现，退还预算
      setNarration(`（这一拍没能送出去：${err.message}。可以再试一次。）`, true);
      refundAction(params.actionType);
      refundCredits(1);
      return;
    }

    // 把 NPC 反应送入 store
    if (params.actionType === "investigate" && params.evidenceIds?.[0]) {
      markInvestigated(params.evidenceIds[0]);
    }

    pushNpcReaction({
      characterId: result.outcome.acceptedNpcAction.characterId,
      text: result.outcome.acceptedNpcAction.resolvedText,
      intent: result.outcome.acceptedNpcAction.speechIntent,
      timestamp: result.outcome.timestamp,
    });
    setNarration(
      `你看到了 ${result.outcome.acceptedNpcAction.resolvedText.replace(/^（|）$/g, "")}`,
      true,
    );

    // 决策 5 触发 L3/L4 提示
    if (result.degraded === "L3" || result.degraded === "L4") {
      setNarration("（灯光闪了一下。这段是脚本接管——但你的选择仍然被记住。）", true);
    }

    const legalEndingId = result.outcome.nextBeat.legalEndingId;
    if (result.outcome.nextBeat.transition === "end_scene" && legalEndingId) {
      finishScene(legalEndingId);
    }
  };

  const finishScene: UseSceneRunnerResult["finishScene"] = (endingId) => {
    setState("scene_ended");
    setNarration(`（场景落幕。结局：${endingId}。）`, true);
  };

  return {
    sceneMeta,
    ready: !!runId && !!sceneMeta && !loading && !runError,
    runError,
    retryRun,
    error,
    handleAction,
    finishScene,
  };
}

// -----------------------------------------------------------------------------
// 初始旁白（每个场景的第一句）
// -----------------------------------------------------------------------------
function initialNarration(sceneId: keyof typeof SCENE_MOCKS): string {
  switch (sceneId) {
    case "photo_lab_2008":
      return "你看到了地下放映室的灯，灯泡把胶片气味烘得更重。阿拉什的手停在工具盒上，没有抬起来。";
    case "farewell_2011":
      return "你看到了出发大厅的不锈钢反光。登机牌攥在她手里——攥到边角都卷起来了。";
    case "reunion_2024":
      return "你看到了雨后老咖啡馆的木门，被人从外面推开。银发与手背细纹，十三年的距离被压成两步。";
    // W12: case_02《莫斯科没有童话》初始旁白
    case "1985_meeting":
      return "你看到了 305 琴房的 Yamaha U3 立式钢琴，1978 年产的榉木在傍晚光线下偏红。伊利亚的红色笔记本夹在夹克内袋，铅笔在总谱上画了三个圈—— И. Б.";
    case "1989_farewell":
      return "你看到了塔甘卡剧院衣帽间 5:30 的挂钟，秒针清晰。5:55 莉莎会从 SVO-2 拨盘电话里说'第三小节是给你的'——娜塔莎会在 4 秒后接起。";
    case "2008_reunion":
      return "你看到了十字山区咖啡馆的老木门，雨后玻璃上有水珠。19:15 伊利亚会抱红色笔记本推门——第 7 页胶带痕迹里有 1989 Aeroflot 标签的边缘。";
  }
  return "";
}
