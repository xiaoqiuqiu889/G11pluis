// =============================================================================
// 莫斯科没有童话 · 场景 3：2008_reunion
// -----------------------------------------------------------------------------
// 柏林 · 十字山区老式咖啡馆 + U1 线 Kreuzberg 站街口（2008-11-15 傍晚）
// 旁观者 UX：雨后玻璃 / 瓷器轻碰 / 21:05 街口分开
// 远期回响：本场景是收束（convergence_summary）
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
import { useSceneRunner } from "@/lib/useSceneRunner";
import { useStore } from "@/lib/store";
import { setCase } from "@/audio/AudioEngine";

const FOCUSES: CameraFocus[] = [
  { id: "wide", label: "十字山区咖啡馆", x: 50, y: 50, zoom: 1 },
  { id: "table", label: "桌面", x: 50, y: 60, zoom: 1.6 },
  { id: "ilya", label: "伊利亚", x: 64, y: 48, zoom: 1.4 },
  { id: "u1", label: "U1 站口", x: 50, y: 30, zoom: 1.5 },
];

const ART_URL = "/assets/images/case_02/atmosphere/03-2008-reunion-kreuzberg-u1-station.png"; // W12-E2E-fix: 走 /assets/ 静态资源根

export default function Reunion2008() {
  if (typeof window !== "undefined") setCase("case_02_moscow_no_fairy_tale");
  const nav = useNavigate();
  const currentState = useStore((s) => s.currentState);
  const currentNarration = useStore((s) => s.currentNarration);

  const [jumping, setJumping] = useState(false);

  const { sceneMeta, ready, runError, retryRun, handleAction, finishScene } = useSceneRunner({
    sceneId: "2008_reunion",
    actorId: "natasha_roschina",
    targetId: "ilya_berman",
    audioChapter: "2008_reunion",
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
    finishScene("ending_crossroads_parting");
    setJumping(true);
  };

  if (jumping) {
    return (
      <SceneTimeJump
        year="第二案 · 完"
        subtitle="卷宗回访入口已开启"
        onDone={() => nav("/cases")}
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
      meta={{ year: "2008 · 11 月 15 日 · 傍晚", location: sceneMeta.location }}
      className="pb-14"
    >
      <ObserverCamera focuses={FOCUSES} defaultFocusId="wide" ariaLabel="十字山区咖啡馆镜头">
        <div className="w-full h-full flex items-center justify-center p-12">
          <div className="w-full max-w-5xl aspect-[2.35/1] relative">
            <div className="absolute inset-0 grid grid-cols-2 grid-rows-2 gap-4">
              <div className="glass rounded p-4 flex flex-col items-center justify-center text-center">
                <p className="t-overline text-amber-glow mb-1">两份节目单</p>
                <p className="t-narration text-paper-200 text-sm">Op.38 / Op.40</p>
                <p className="t-meta text-paper-100/40 mt-1">19:30 在桌面对齐</p>
              </div>
              <div className="glass rounded p-4 flex flex-col items-center justify-center text-center">
                <p className="t-overline text-amber-glow mb-1">红色笔记本</p>
                <p className="t-narration text-paper-200 text-sm">第 7 页胶带痕迹</p>
                <p className="t-meta text-paper-100/40 mt-1">Aeroflot 标签边缘</p>
              </div>
              <div className="glass rounded p-4 flex flex-col items-center justify-center text-center">
                <p className="t-overline text-amber-glow mb-1">1995 明信片</p>
                <p className="t-narration text-paper-200 text-sm">维也纳未寄</p>
                <p className="t-meta text-paper-100/40 mt-1">13 年后被打开</p>
              </div>
              <div className="glass rounded p-4 flex flex-col items-center justify-center text-center">
                <p className="t-overline text-amber-glow mb-1">U1 站口</p>
                <p className="t-narration text-paper-200 text-sm">21:05 红灯变绿</p>
                <p className="t-meta text-paper-100/40 mt-1">两人走向不同方向</p>
              </div>
            </div>
          </div>
        </div>
      </ObserverCamera>

      <div className="absolute top-28 right-6 z-20 flex flex-col gap-2 max-w-xs">
        <StateFlux tone="warm" note="雨后玻璃水珠 / 瓷器轻碰" />
      </div>

      <ObserverHint trigger="critical_moment" pov="ilya_berman" delayMs={8000} />
      <ObserverHint trigger="after_choice" pov="natasha_roschina" delayMs={4000} />

      <div className="absolute bottom-16 left-0 right-0 z-20 px-6">
        <div className="max-w-4xl mx-auto mb-3">
          <ObserverNarration text={currentNarration} />
        </div>
      </div>

      <div className="absolute bottom-32 right-6 z-20 w-80 max-h-72">
        <NPCReactions />
      </div>

      <div className="absolute bottom-32 left-6 z-20 w-[28rem] max-w-[42vw]">
        <InvestigationPanel
          objects={sceneMeta.investigatableObjects}
          budget={sceneMeta.turnBudget.investigate ?? 3}
          onInvestigate={onInvestigate}
        />
      </div>

      <div className="absolute bottom-0 left-0 right-0 z-20 px-6 pb-20">
        <div className="max-w-4xl mx-auto">
          <ActionBar
            onAct={(p) => void handleAction(p)}
            contextActions={{
              give: { label: "把 Op.40 节目单放在桌面对齐", targetId: "ilya_berman" },
              reveal: { label: "把 1995 明信片从斜挎包取出", targetId: "postcard_wien_1995" },
              question: { label: "问'5:55 你让莉莎传话吗'", targetId: "ilya_berman" },
              comfort: { label: "承认'我在 4 秒后才接'", targetId: "ilya_berman" },
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
            <h2 className="t-display text-2xl mb-4">21:05 · 街口分开</h2>
            <p className="t-narration text-paper-200 mb-6">
              （红灯变绿。两人走向不同方向。19 年在那一刻被收入红色笔记本第 7 页胶带痕迹里——莉莎的电话、马蒂亚斯的合唱团、阿尼娅的蜡笔红星都还在。）
            </p>
            <div className="flex justify-center gap-2">
              <button className="action-btn" onClick={() => nav("/archive")}>
                打开卷宗
              </button>
              <button className="action-btn border-amber-glow text-amber-glow" onClick={onEnd}>
                ✓ 完成第二案
              </button>
            </div>
          </div>
        </div>
      )}
    </CinematicFrame>
  );
}
