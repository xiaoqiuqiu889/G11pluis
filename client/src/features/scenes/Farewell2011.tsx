// =============================================================================
// 革命街没有尽头 · 场景 2：farewell_2011
// -----------------------------------------------------------------------------
// 德黑兰国际机场·出发大厅（2011 秋）
// 决策 3：必须引用 photo_lab_2008 至少一项具体行为
// ============================================================================

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CinematicFrame } from "@/components/CinematicFrame";
import { InvestigationPanel } from "@/components/InvestigationPanel";
import { ActionBar } from "@/components/ActionBar";
import { NPCReactions } from "@/components/NPCReactions";
import { SceneTimeJump } from "@/components/SceneTimeJump";
import { SceneStatusBar } from "@/components/SceneStatusBar";
import { ObserverNarration, StateFlux } from "@/features/observer/ObserverNarration";
import { ObserverCamera, type CameraFocus } from "@/features/observer/ObserverCamera";
import { ObserverHint } from "@/features/observer/ObserverHint";
import { POVSwitcher } from "@/features/observer/POVSwitcher";
import { useSceneRunner } from "@/lib/useSceneRunner";
import { useStore } from "@/lib/store";

const FOCUSES: CameraFocus[] = [
  { id: "wide", label: "全景", x: 50, y: 50, zoom: 1 },
  { id: "leila", label: "莱拉", x: 38, y: 52, zoom: 1.5 },
  { id: "arash", label: "阿拉什", x: 62, y: 48, zoom: 1.5 },
  { id: "board", label: "航班板", x: 80, y: 22, zoom: 1.7 },
];

const ART_URL = "/assets/images/atmosphere/A2-farewell-2011-airport.png"; // W12-E2E-fix: 走 /assets/ 静态资源根

export default function Farewell2011() {
  const nav = useNavigate();
  const currentState = useStore((s) => s.currentState);
  const currentNarration = useStore((s) => s.currentNarration);
  const [jumping, setJumping] = useState(false);

  const { sceneMeta, ready, runError, retryRun, handleAction, finishScene } = useSceneRunner({
    sceneId: "farewell_2011",
    actorId: "leila",
    targetId: "arash",
    audioChapter: "chapter3",
  });

  const onInvestigate = (obj: { id: string; name: string; description: string }) => {
    void handleAction({
      actionType: "investigate",
      utterance: obj.name,
      tone: "neutral",
      evidenceIds: [obj.id],
    });
  };

  const onEnd = () => {
    finishScene("kept_back");
    setJumping(true);
  };

  if (jumping) {
    return (
      <SceneTimeJump
        year="2024 · 秋"
        subtitle="伊斯坦布尔·卡拉柯伊老咖啡馆"
        onDone={() => nav("/scene/reunion_2024")}
      />
    );
  }

  if (!sceneMeta) {
    return (
      <div className="cinematic-frame">
        <div className="vignette" />
        <div className="cinematic-aspect">
          <p className="t-narration text-paper-200">（正在把场景打开——）</p>
        </div>
      </div>
    );
  }

  return (
    <CinematicFrame
      background={ART_URL}
      meta={{ year: "2011 · 秋", location: sceneMeta.location }}
      className="pb-14"
    >
      <ObserverCamera focuses={FOCUSES} defaultFocusId="wide" ariaLabel="机场出发大厅镜头">
        <SceneStage meta={sceneMeta} />
      </ObserverCamera>

      <div className="absolute top-12 right-6 z-20">
        <POVSwitcher />
      </div>

      <div className="absolute top-28 right-6 z-20 flex flex-col gap-2 max-w-xs">
        <StateFlux tone="strained" note="广播混响 + 行李箱滚轮" />
        <p className="t-meta text-amber-glow/70 text-[10px] max-w-[16rem] leading-relaxed">
          提示：本场景必触发 photo_lab_2008 至少一项具体行为。
        </p>
      </div>

      <ObserverHint trigger="critical_moment" pov="arash" delayMs={6000} />

      <div className="absolute bottom-16 left-0 right-0 z-20 px-6">
        <div className="max-w-4xl mx-auto mb-3">
          <ObserverNarration text={currentNarration} typewriter />
        </div>
      </div>

      <div className="absolute bottom-32 right-6 z-20 w-80 max-h-72">
        <NPCReactions />
      </div>

      <div className="absolute bottom-32 left-6 z-20 w-[28rem] max-w-[42vw]">
        <InvestigationPanel
          objects={sceneMeta.investigatableObjects}
          budget={sceneMeta.turnBudget.investigate ?? 2}
          onInvestigate={onInvestigate}
          disabled={!ready}
        />
      </div>

      <div className="absolute bottom-0 left-0 right-0 z-20 px-6 pb-20">
        <div className="max-w-4xl mx-auto">
          <ActionBar
            onAct={(p) => void handleAction(p)}
            contextActions={{
              give: { label: "把某样东西交给他", targetId: "arash" },
              comfort: { label: "安抚阿拉什", targetId: "arash" },
              question: { label: "问阿拉什", targetId: "arash" },
              confront: { label: "直面阿拉什", targetId: "arash" },
            }}
          ready={ready}
            runError={runError}
            onRetryRun={retryRun}
          />
        </div>
      </div>

      <SceneStatusBar />

      {currentState === "scene_ended" && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-ink-900/70 backdrop-blur">
          <div className="glass-strong p-8 max-w-md text-center">
            <p className="t-overline text-amber-glow mb-2">场景结束</p>
            <h2 className="t-display text-2xl mb-4">在登机口之前</h2>
            <p className="t-narration text-paper-200 mb-6">
              （广播响了。她没回头——他也没追。行李牌背面的字，要到十三年后才被街上的人念出来。）
            </p>
            <div className="flex justify-center gap-2">
              <button className="action-btn" onClick={() => nav("/archive")}>
                打开卷宗
              </button>
              <button className="action-btn border-amber-glow text-amber-glow" onClick={onEnd}>
                时间跳转 · 2024
              </button>
            </div>
          </div>
        </div>
      )}
    </CinematicFrame>
  );
}

function SceneStage({ meta }: { meta: NonNullable<ReturnType<typeof useStore.getState>["sceneMeta"]> }) {
  return (
    <div className="w-full h-full flex items-center justify-center p-12">
      <div className="w-full max-w-5xl aspect-[2.35/1] relative">
        <div className="absolute inset-0 grid grid-cols-3 grid-rows-2 gap-4">
          <div className="col-span-1 row-span-1 glass rounded p-4 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">上方</p>
              <p className="t-narration text-paper-200 text-sm">航班板</p>
              <p className="t-meta text-paper-100/40 mt-1">抽象 · 时间在走</p>
            </div>
          </div>
          <div className="col-span-1 row-span-1 glass rounded p-4 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">中央</p>
              <p className="t-narration text-paper-200 text-sm">值机柜台</p>
              <p className="t-meta text-paper-100/40 mt-1">时钟秒针</p>
            </div>
          </div>
          <div className="col-span-1 row-span-1 glass rounded p-4 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">远处</p>
              <p className="t-narration text-paper-200 text-sm">登机口</p>
              <p className="t-meta text-paper-100/40 mt-1">广播将响</p>
            </div>
          </div>
          <div className="col-span-1 row-span-1 glass rounded p-4 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">在场的</p>
              <p className="t-narration text-paper-200 text-sm">莱拉 · 行李箱</p>
              <p className="t-meta text-paper-100/40 mt-1">登机牌攥在右手</p>
            </div>
          </div>
          <div className="col-span-1 row-span-1 glass rounded p-4 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">在场的</p>
              <p className="t-narration text-paper-200 text-sm">阿拉什 · 门卡</p>
              <p className="t-meta text-paper-100/40 mt-1">外套口袋有折诗</p>
            </div>
          </div>
          <div className="col-span-1 row-span-1 glass rounded p-4 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">提示</p>
              <p className="t-narration text-paper-200 text-sm">不直说</p>
              <p className="t-meta text-paper-100/40 mt-1">三件事分开说</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
