// =============================================================================
// 莫斯科没有童话 · 场景 1：1985_meeting
// -----------------------------------------------------------------------------
// 莫斯科音乐学院 · 305 琴房与两份同版手抄谱（1985 秋）
// 旁观者 UX：电影感构图、宽银幕 2.35:1
// 跨年代种子：seed_ilya_pencil_page_in_notebook / seed_manuscript_stays_in_305 / seed_natasha_keeps_manuscript
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
  { id: "wide", label: "305 琴房", x: 50, y: 50, zoom: 1 },
  { id: "piano", label: "Yamaha U3", x: 50, y: 60, zoom: 1.6 },
  { id: "ilya", label: "伊利亚", x: 64, y: 48, zoom: 1.4 },
  { id: "manuscript", label: "总谱", x: 36, y: 40, zoom: 1.5 },
];

const ART_URL = "/assets/images/case_02/atmosphere/01-1985-meeting-moscow-conservatory-hallway.png"; // W12-E2E-fix: 走 /assets/ 静态资源根

export default function Meeting1985() {
  if (typeof window !== "undefined") setCase("case_02_moscow_no_fairy_tale");
  const nav = useNavigate();
  const currentState = useStore((s) => s.currentState);
  const currentNarration = useStore((s) => s.currentNarration);

  const [jumping, setJumping] = useState(false);

  const { sceneMeta, ready, runError, retryRun, handleAction, finishScene } = useSceneRunner({
    sceneId: "1985_meeting",
    actorId: "natasha_roschina",
    targetId: "ilya_berman",
    audioChapter: "1985_meeting",
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
    finishScene("ending_parting_at_door");
    setJumping(true);
  };

  if (jumping) {
    return (
      <SceneTimeJump
        year="1989-04-08 · 清晨"
        subtitle="莫斯科谢列梅捷沃机场 SVO-2"
        onDone={() => nav("/scene/1989_farewell")}
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
      meta={{ year: "1985 · 秋", location: sceneMeta.location }}
      className="pb-14"
    >
      <ObserverCamera focuses={FOCUSES} defaultFocusId="wide" ariaLabel="305 琴房镜头">
        <div className="w-full h-full flex items-center justify-center p-12">
          <div className="w-full max-w-5xl aspect-[2.35/1] relative">
            <div className="absolute inset-0 grid grid-cols-2 grid-rows-2 gap-4">
              <div className="glass rounded p-4 flex flex-col items-center justify-center text-center">
                <p className="t-overline text-amber-glow mb-1">排练</p>
                <p className="t-narration text-paper-200 text-sm">肖斯塔科维奇 Op.38</p>
                <p className="t-meta text-paper-100/40 mt-1">第二乐章中段</p>
              </div>
              <div className="glass rounded p-4 flex flex-col items-center justify-center text-center">
                <p className="t-overline text-amber-glow mb-1">总谱</p>
                <p className="t-narration text-paper-200 text-sm">铅笔圈三小节</p>
                <p className="t-meta text-paper-100/40 mt-1">伊利亚签 И. Б.</p>
              </div>
              <div className="glass rounded p-4 flex flex-col items-center justify-center text-center">
                <p className="t-overline text-amber-glow mb-1">大提琴</p>
                <p className="t-narration text-paper-200 text-sm">Petrof 1962</p>
                <p className="t-meta text-paper-100/40 mt-1">松香渍在中央 C 键</p>
              </div>
              <div className="glass rounded p-4 flex flex-col items-center justify-center text-center">
                <p className="t-overline text-amber-glow mb-1">笔记本</p>
                <p className="t-narration text-paper-200 text-sm">红色笔记本</p>
                <p className="t-meta text-paper-100/40 mt-1">1985 第 1 页</p>
              </div>
            </div>
          </div>
        </div>
      </ObserverCamera>

      <div className="absolute top-28 right-6 z-20 flex flex-col gap-2 max-w-xs">
        <StateFlux tone="warm" note="305 琴房傍晚，榉木偏红" />
      </div>

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
              give: { label: "把总谱交给伊利亚", targetId: "ilya_berman" },
              comfort: { label: "安抚伊利亚", targetId: "ilya_berman" },
              question: { label: "问伊利亚", targetId: "ilya_berman" },
              reveal: { label: "撕下 И. Б. 圈注页", targetId: "manuscript_op38" },
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
            <h2 className="t-display text-2xl mb-4">21:40 · 305 琴房锁舌咔哒</h2>
            <p className="t-narration text-paper-200 mb-6">
              （琴房管理员敲门。两个人各自离开。手抄谱的命运已经被决定——4 年后 SVO-2 会再被打开。）
            </p>
            <div className="flex justify-center gap-2">
              <button className="action-btn border-amber-glow text-amber-glow" onClick={onEnd}>
                时间跳转 · 1989 SVO-2
              </button>
            </div>
          </div>
        </div>
      )}
    </CinematicFrame>
  );
}
