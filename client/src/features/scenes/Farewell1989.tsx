// =============================================================================
// 莫斯科没有童话 · 场景 2：1989_farewell
// -----------------------------------------------------------------------------
// 莫斯科谢列梅捷沃机场 SVO-2 + 塔甘卡剧院衣帽间（1989-04-08 清晨）
// 旁观者 UX：双视角交叉 / 5:55 电话 / 6:15 登机广播
// 跨年代种子：seed_lisa_relays_third_bar / seed_walkman_tape_in_1989_luggage / seed_aeroflot_tag_in_page_7
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
  { id: "wide", label: "SVO-2 出境大厅", x: 50, y: 50, zoom: 1 },
  { id: "tag", label: "Aeroflot 标签", x: 36, y: 60, zoom: 1.6 },
  { id: "ilya", label: "伊利亚", x: 64, y: 48, zoom: 1.4 },
  { id: "payphone", label: "付费电话亭", x: 50, y: 30, zoom: 1.5 },
];

const ART_URL = "/assets/images/case_02/atmosphere/02-1989-farewell-svo2-airport.png"; // W12-E2E-fix: 走 /assets/ 静态资源根

export default function Farewell1989() {
  if (typeof window !== "undefined") setCase("case_02_moscow_no_fairy_tale");
  const nav = useNavigate();
  const currentState = useStore((s) => s.currentState);
  const currentNarration = useStore((s) => s.currentNarration);

  const [jumping, setJumping] = useState(false);

  const { sceneMeta, handleAction, finishScene } = useSceneRunner({
    sceneId: "1989_farewell",
    actorId: "natasha_roschina",
    targetId: "lisa_hoffmann",
    audioChapter: "1989_farewell",
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
    finishScene("ending_su355_takeoff");
    setJumping(true);
  };

  if (jumping) {
    return (
      <SceneTimeJump
        year="2008-11-15 · 傍晚"
        subtitle="柏林 · 十字山区老式咖啡馆 + U1 线街口"
        onDone={() => nav("/scene/2008_reunion")}
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
      meta={{ year: "1989 · 4 月 8 日 · 清晨", location: sceneMeta.location }}
      className="pb-14"
    >
      <ObserverCamera focuses={FOCUSES} defaultFocusId="wide" ariaLabel="SVO-2 镜头">
        <div className="w-full h-full flex items-center justify-center p-12">
          <div className="w-full max-w-5xl aspect-[2.35/1] relative">
            <div className="absolute inset-0 grid grid-cols-2 grid-rows-2 gap-4">
              <div className="glass rounded p-4 flex flex-col items-center justify-center text-center">
                <p className="t-overline text-amber-glow mb-1">航班板</p>
                <p className="t-narration text-paper-200 text-sm">SU-355 / PRG / VIE</p>
                <p className="t-meta text-paper-100/40 mt-1">6:15 起飞</p>
              </div>
              <div className="glass rounded p-4 flex flex-col items-center justify-center text-center">
                <p className="t-overline text-amber-glow mb-1">行李</p>
                <p className="t-narration text-paper-200 text-sm">Aeroflot 标签</p>
                <p className="t-meta text-paper-100/40 mt-1">SU-355 / 1989-04-08</p>
              </div>
              <div className="glass rounded p-4 flex flex-col items-center justify-center text-center">
                <p className="t-overline text-amber-glow mb-1">电话亭</p>
                <p className="t-narration text-paper-200 text-sm">5:55 莉莎拨盘</p>
                <p className="t-meta text-paper-100/40 mt-1">第三小节是给你的</p>
              </div>
              <div className="glass rounded p-4 flex flex-col items-center justify-center text-center">
                <p className="t-overline text-amber-glow mb-1">塔甘卡</p>
                <p className="t-narration text-paper-200 text-sm">衣帽间 5:30</p>
                <p className="t-meta text-paper-100/40 mt-1">萨沙把手放在娜塔莎肩上</p>
              </div>
            </div>
          </div>
        </div>
      </ObserverCamera>

      <div className="absolute top-28 right-6 z-20 flex flex-col gap-2 max-w-xs">
        <StateFlux tone="cold" note="SVO-2 荧光灯嗡鸣 / 传送带机械" />
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
              give: { label: "接过 walkman 磁带", targetId: "ilya_berman" },
              reveal: { label: "翻红色笔记本第 1 页", targetId: "red_notebook_ilya_1989" },
              silence: { label: "5:55 电话响铃后沉默 4 秒", targetId: "natasha_home_phone" },
              comfort: { label: "问萨沙为什么没去机场", targetId: "sasha_kuzmin" },
            }}
          />
        </div>
      </div>

      <SceneStatusBar />

      {currentState === "scene_ended" && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-ink-900/70 backdrop-blur">
          <div className="glass-strong p-8 max-w-md text-center">
            <p className="t-overline text-amber-glow mb-2">场景结束</p>
            <h2 className="t-display text-2xl mb-4">6:15 · SU-355 起飞</h2>
            <p className="t-narration text-paper-200 mb-6">
              （登机广播响起。第三小节已经被说出。19 年后会在柏林十字山区被打开。）
            </p>
            <div className="flex justify-center gap-2">
              <button className="action-btn border-amber-glow text-amber-glow" onClick={onEnd}>
                时间跳转 · 2008 柏林
              </button>
            </div>
          </div>
        </div>
      )}
    </CinematicFrame>
  );
}
