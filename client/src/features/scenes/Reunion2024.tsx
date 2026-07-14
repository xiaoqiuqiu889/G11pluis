// =============================================================================
// 革命街没有尽头 · 场景 3：reunion_2024
// -----------------------------------------------------------------------------
// 伊斯坦布尔·卡拉柯伊老咖啡馆与路口（2024 秋）
// 决策 3：必须显式引用 photo_lab_2008 + farewell_2011 至少各一项
// NPC 必须主动提起玩家 2008 / 2011 的具体行为
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
  { id: "arash", label: "阿拉什", x: 60, y: 45, zoom: 1.4 },
  { id: "leila", label: "莱拉", x: 36, y: 50, zoom: 1.4 },
  { id: "table", label: "桌面", x: 50, y: 65, zoom: 1.7 },
  { id: "door", label: "木门", x: 50, y: 22, zoom: 1.5 },
];

const ART_URL = "art-v5/istanbul-cafe-photo-close.png";

export default function Reunion2024() {
  const nav = useNavigate();
  const currentState = useStore((s) => s.currentState);
  const currentNarration = useStore((s) => s.currentNarration);
  const [jumping, setJumping] = useState(false);

  const { sceneMeta, handleAction, finishScene } = useSceneRunner({
    sceneId: "reunion_2024",
    actorId: "leila",
    targetId: "arash",
    audioChapter: "chapter5",
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
    finishScene("open_crossroad");
    setJumping(true);
  };

  if (jumping) {
    return (
      <SceneTimeJump
        year="尾声 · 街口分开"
        subtitle="绿灯亮起"
        onDone={() => nav("/")}
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
      meta={{ year: "2024 · 秋", location: sceneMeta.location }}
      className="pb-14"
    >
      <ObserverCamera focuses={FOCUSES} defaultFocusId="wide" ariaLabel="伊斯坦布尔咖啡馆镜头">
        <SceneStage meta={sceneMeta} />
      </ObserverCamera>

      <div className="absolute top-12 right-6 z-20">
        <POVSwitcher />
      </div>

      <div className="absolute top-28 right-6 z-20 flex flex-col gap-2 max-w-xs">
        <StateFlux tone="intimate" note="雨后木门 + 铜勺碰糖罐" />
        <p className="t-meta text-amber-glow/70 text-[10px] max-w-[16rem] leading-relaxed">
          提示：远期回响收束；NPC 主动提起 2008 / 2011 具体行为。
        </p>
      </div>

      <ObserverHint trigger="critical_moment" pov="leila" delayMs={5000} />
      <ObserverHint trigger="scene_end" pov="arash" delayMs={10000} />

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
        />
      </div>

      <div className="absolute bottom-0 left-0 right-0 z-20 px-6 pb-20">
        <div className="max-w-4xl mx-auto">
          <ActionBar
            onAct={(p) => void handleAction(p)}
            contextActions={{
              give: { label: "把照片放在桌上", targetId: "arash" },
              comfort: { label: "安抚阿拉什", targetId: "arash" },
              question: { label: "问阿拉什", targetId: "arash" },
              confront: { label: "直面这十三年", targetId: "arash" },
            }}
          />
        </div>
      </div>

      <SceneStatusBar />

      {currentState === "scene_ended" && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-ink-900/70 backdrop-blur">
          <div className="glass-strong p-8 max-w-md text-center">
            <p className="t-overline text-amber-glow mb-2">场景结束</p>
            <h2 className="t-display text-2xl mb-4">路口分开</h2>
            <p className="t-narration text-paper-200 mb-6">
              （绿灯亮起。糖罐里的铜勺还在震。两张照片在桌面上对齐了又滑开——他们走向不同的方向。）
            </p>
            <div className="flex justify-center gap-2">
              <button className="action-btn" onClick={() => nav("/archive")}>
                打开卷宗
              </button>
              <button
                className="action-btn border-amber-glow text-amber-glow"
                onClick={() => nav("/paywall/keepsake")}
              >
                私人纪念品
              </button>
              <button className="action-btn" onClick={onEnd}>
                回到街上
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
        <div className="absolute inset-0 grid grid-cols-4 grid-rows-2 gap-3">
          <div className="col-span-1 row-span-1 glass rounded p-3 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">门口</p>
              <p className="t-narration text-paper-200 text-sm">木门</p>
            </div>
          </div>
          <div className="col-span-1 row-span-1 glass rounded p-3 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">桌</p>
              <p className="t-narration text-paper-200 text-sm">糖罐 · 铜勺</p>
            </div>
          </div>
          <div className="col-span-1 row-span-1 glass rounded p-3 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">在场的</p>
              <p className="t-narration text-paper-200 text-sm">阿拉什 · 35</p>
              <p className="t-meta text-paper-100/40 mt-1">诗集抱在臂弯</p>
            </div>
          </div>
          <div className="col-span-1 row-span-1 glass rounded p-3 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">在场的</p>
              <p className="t-narration text-paper-200 text-sm">莱拉 · 35</p>
              <p className="t-meta text-paper-100/40 mt-1">手机贴着桌面</p>
            </div>
          </div>
          <div className="col-span-2 row-span-1 glass rounded p-3 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">在桌上</p>
              <p className="t-narration text-paper-200 text-sm">两张同版照片 + 一本鲁米诗集</p>
              <p className="t-meta text-paper-100/40 mt-1">（如果对齐了——）</p>
            </div>
          </div>
          <div className="col-span-2 row-span-1 glass rounded p-3 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">街口</p>
              <p className="t-narration text-paper-200 text-sm">绿灯</p>
              <p className="t-meta text-paper-100/40 mt-1">机场方向牌 · 雨后</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
