// =============================================================================
// 革命街没有尽头 · 共享场景 Hook
// -----------------------------------------------------------------------------
// - 加载 SceneMeta
// - 提交动作（mock 模式 / 真服务端）
// - 处理转场、付费墙触发、降级
// ============================================================================

import { useEffect, useState } from "react";
import { useStore } from "@/lib/store";
import { SCENE_MOCKS } from "@/mocks/scenes";
import { mockSubmitTurn } from "@/lib/api";
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
  loading: boolean;
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
  const sceneMeta = useStore((s) => s.sceneMeta);
  const loadScene = useStore((s) => s.loadScene);
  const markInvestigated = useStore((s) => s.markInvestigated);
  const spendAction = useStore((s) => s.spendAction);
  const fireSeed = useStore((s) => s.fireSeed);
  const holdArtifact = useStore((s) => s.holdArtifact);
  const pushNpcReaction = useStore((s) => s.pushNpcReaction);
  const setNarration = useStore((s) => s.setNarration);
  const setRun = useStore((s) => s.setRun);
  const setState = useStore((s) => s.setState);
  const spendCredits = useStore((s) => s.spendCredits);
  const openPaywall = useStore((s) => s.openPaywall);
  const audioEnabled = useStore((s) => s.audioEnabled);
  const runId = useStore((s) => s.runId);
  const lastEventSequence = useStore((s) => s.lastEventSequence);
  const credits = useStore((s) => s.credits);

  // 加载场景 meta
  useEffect(() => {
    const meta = SCENE_MOCKS[sceneId];
    if (!meta) {
      setError(`未找到场景 ${sceneId}`);
      setLoading(false);
      return;
    }
    loadScene(meta);
    if (!runId) {
      setRun(crypto.randomUUID(), sceneId as SceneId);
    }
    if (audioEnabled && audioChapter) {
      void audioEngine.start(audioChapter);
    }
    setLoading(false);
    // 初始旁白
    setNarration(initialNarration(sceneId), true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sceneId]);

  // 动作：检查积分、检查预算、提交
  const handleAction: UseSceneRunnerResult["handleAction"] = async (params) => {
    // 积分检查（决策 4：免费样章 30 积分，1 主调用 = 1 积分）
    if (credits <= 0) {
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
    // 调查：标记为已调查
    if (params.actionType === "investigate" && params.evidenceIds?.[0]) {
      markInvestigated(params.evidenceIds[0]);
    }
    // 给出/销毁：持有/失去物件
    if (params.actionType === "give" && params.evidenceIds?.[0]) {
      holdArtifact(params.evidenceIds[0]);
    }

    spendAction(params.actionType);
    spendCredits(1);

    // 提交（mock 模式）
    const action = {
      runId: useStore.getState().runId!,
      sceneId,
      actionType: params.actionType,
      actorId,
      targetId: params.targetId ?? targetId ?? null,
      evidenceIds: params.evidenceIds ?? [],
      utterance: params.utterance,
      tone: params.tone,
      disclosureLevel: 0.5,
      isDeceptive: false,
    };

    // 决策 5：先用 mock 联调；真服务端模式可切换
    const result = await mockSubmitTurn({
      runId: action.runId,
      sceneId: action.sceneId,
      clientActionId: crypto.randomUUID(),
      expectedEventSequence: lastEventSequence + 1,
      actionType: action.actionType,
      actorId: action.actorId,
      targetId: action.targetId,
      evidenceIds: action.evidenceIds,
      utterance: action.utterance,
      tone: action.tone,
      disclosureLevel: action.disclosureLevel,
      isDeceptive: action.isDeceptive,
      clientTimestamp: new Date().toISOString(),
      schemaVersion: "1.0.0",
    });

    // 把 NPC 反应送入 store
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

    // 触发种子（mock 简化为：give 行为触发 photo_in_pocket/book）
    if (params.actionType === "give") {
      if (params.evidenceIds?.includes("photo_pair")) {
        fireSeed("photo_in_pocket");
      }
    }

    // 决策 5 触发 L3/L4 提示
    if (result.degraded === "L3" || result.degraded === "L4") {
      setNarration("（灯光闪了一下。这段是脚本接管——但你的选择仍然被记住。）", true);
    }
  };

  const finishScene: UseSceneRunnerResult["finishScene"] = (endingId) => {
    setState("scene_ended");
    setNarration(`（场景落幕。结局：${endingId}。）`, true);
  };

  return {
    sceneMeta,
    loading,
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
  }
  return "";
}

// -----------------------------------------------------------------------------
// 抑制未使用警告
// -----------------------------------------------------------------------------
