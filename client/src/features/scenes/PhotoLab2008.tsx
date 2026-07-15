// =============================================================================
// 革命街没有尽头 · 场景 1：photo_lab_2008
// -----------------------------------------------------------------------------
// 革命街地下放映室与两张同版毕业照（2008 夏，德黑兰）
// 旁观者 UX：电影感构图、宽银幕 2.35:1
// 调查：7 个可调查对象；行为预算 investigate=3
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

// 镜头焦点（不是 UI 焦点，是 ObserverCamera 的空间焦点）
const FOCUSES: CameraFocus[] = [
  { id: "wide", label: "全景", x: 50, y: 50, zoom: 1 },
  { id: "photo", label: "照片", x: 36, y: 62, zoom: 1.6 },
  { id: "arash", label: "阿拉什", x: 64, y: 48, zoom: 1.4 },
  { id: "projector", label: "放映机", x: 50, y: 30, zoom: 1.5 },
];

const ART_URL = "/assets/images/atmosphere/A1-photo-lab-2008-basement.png"; // W12-E2E-fix: 走 /assets/ 静态资源根

export default function PhotoLab2008() {
  const nav = useNavigate();
  const currentState = useStore((s) => s.currentState);
  const currentNarration = useStore((s) => s.currentNarration);

  const [jumping, setJumping] = useState(false);

  const { sceneMeta, handleAction, finishScene } = useSceneRunner({
    sceneId: "photo_lab_2008",
    actorId: "leila",
    targetId: "arash",
    audioChapter: "chapter1",
  });

  const onInvestigate = (obj: { id: string; name: string; description: string }) => {
    void handleAction({
      actionType: "investigate",
      utterance: obj.name,
      tone: "neutral",
      evidenceIds: [obj.id],
    });
  };

  // 场景结束 → 时间跳转到 2011
  const onEnd = () => {
    finishScene("shared_secret");
    setJumping(true);
  };

  if (jumping) {
    return (
      <SceneTimeJump
        year="2011 · 秋"
        subtitle="德黑兰国际机场·国际出发大厅"
        onDone={() => nav("/scene/farewell_2011")}
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
      meta={{ year: "2008 · 夏", location: sceneMeta.location }}
      bulbFlicker
      className="pb-14"
    >
      <ObserverCamera focuses={FOCUSES} defaultFocusId="wide" ariaLabel="地下放映室镜头">
        <SceneStage meta={sceneMeta} />
      </ObserverCamera>

      <div className="absolute top-12 right-6 z-20">
        <POVSwitcher />
      </div>

      <div className="absolute top-28 right-6 z-20 flex flex-col gap-2 max-w-xs">
        <StateFlux tone="warm" note="灯泡烘得空气发甜" />
      </div>

      <ObserverHint trigger="critical_moment" pov="arash" delayMs={8000} />
      <ObserverHint trigger="after_choice" pov="leila" delayMs={4000} />

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
          budget={sceneMeta.turnBudget.investigate ?? 3}
          onInvestigate={onInvestigate}
        />
      </div>

      <div className="absolute bottom-0 left-0 right-0 z-20 px-6 pb-20">
        <div className="max-w-4xl mx-auto">
          <ActionBar
            onAct={(p) => void handleAction(p)}
            contextActions={{
              give: { label: "把照片交给阿拉什", targetId: "arash" },
              comfort: { label: "安抚阿拉什", targetId: "arash" },
              question: { label: "问阿拉什", targetId: "arash" },
              confront: { label: "直面阿拉什", targetId: "arash" },
            }}
          />
        </div>
      </div>

      <SceneStatusBar />

      {currentState === "scene_ended" && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-ink-900/70 backdrop-blur">
          <div className="glass-strong p-8 max-w-md text-center">
            <p className="t-overline text-amber-glow mb-2">场景结束</p>
            <h2 className="t-display text-2xl mb-4">这一夜走完了</h2>
            <p className="t-narration text-paper-200 mb-6">
              （灯泡暗下来。放映机的低频慢慢停下。照片已经被分到两个不同的手里——接下来是十三年的别处。）
            </p>
            <div className="flex justify-center gap-2">
              <button className="action-btn" onClick={() => nav("/archive")}>
                打开卷宗
              </button>
              <button
                className="action-btn border-amber-glow text-amber-glow"
                onClick={onEnd}
              >
                时间跳转 · 2011
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
        {/* 地下放映室"想象"：分镜布局 */}
        <div className="absolute inset-0 grid grid-cols-3 grid-rows-2 gap-4">
          {/* 左上：放映机 / 灯泡 */}
          <div className="col-span-1 row-span-1 glass rounded p-4 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">投影</p>
              <p className="t-narration text-paper-200 text-sm">16mm 放映机</p>
              <p className="t-meta text-paper-100/40 mt-1">灯泡刚被点亮</p>
            </div>
          </div>
          {/* 中上：诗集 / 工具盒 */}
          <div className="col-span-1 row-span-1 glass rounded p-4 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">桌面</p>
              <p className="t-narration text-paper-200 text-sm">鲁米诗集 + 工具盒</p>
              <p className="t-meta text-paper-100/40 mt-1">书脊开裂 · 油渍</p>
            </div>
          </div>
          {/* 右上：莱拉（侧影） */}
          <div className="col-span-1 row-span-1 glass rounded p-4 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">在场的</p>
              <p className="t-narration text-paper-200 text-sm">莱拉 · 21 岁</p>
              <p className="t-meta text-paper-100/40 mt-1">手里抱着牛皮纸袋</p>
            </div>
          </div>
          {/* 左下：照片 / 同版 */}
          <div className="col-span-1 row-span-1 glass rounded p-4 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">关键</p>
              <p className="t-narration text-paper-200 text-sm">两张同版照片</p>
              <p className="t-meta text-paper-100/40 mt-1">仍在贴合</p>
            </div>
          </div>
          {/* 中下：阿拉什（手/工具） */}
          <div className="col-span-1 row-span-1 glass rounded p-4 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">在场的</p>
              <p className="t-narration text-paper-200 text-sm">阿拉什 · 22 岁</p>
              <p className="t-meta text-paper-100/40 mt-1">手停在工具盒上</p>
            </div>
          </div>
          {/* 右下：大刚 / 摄影师 */}
          <div className="col-span-1 row-span-1 glass rounded p-4 flex items-center justify-center text-center">
            <div>
              <p className="t-overline text-amber-glow mb-1">在场的</p>
              <p className="t-narration text-paper-200 text-sm">大刚 · 摄影师</p>
              <p className="t-meta text-paper-100/40 mt-1">夹着半根没点的烟</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
