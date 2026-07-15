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
  const worldSnapshot = useStore((s) => s.worldSnapshot);
  const causalSeedsActive = useStore((s) => s.causalSeedsActive);
  const pendingAction = useStore((s) => s.pendingAction);

  const [jumping, setJumping] = useState(false);
  const [showOtherActions, setShowOtherActions] = useState(false);

  const { sceneMeta, ready, runError, retryRun, handleAction } = useSceneRunner({
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

  const authoritativeEndingId = worldSnapshot?.canonicalState.endingId ?? null;
  const photoSeedIds = new Set(causalSeedsActive.map((seed) => seed.id));
  const keptBoth =
    authoritativeEndingId === "one_sided_memory" || photoSeedIds.has("both_photos_with_one");
  const splitPhotos =
    authoritativeEndingId === "shared_secret" ||
    (photoSeedIds.has("photo_in_pocket") && photoSeedIds.has("photo_in_book"));
  const photoConsequence = keptBoth
    ? "两张照片都在莱拉的包里；阿拉什没有照片。"
    : splitPhotos
      ? "莱拉的包里一张，阿拉什的诗集里一张。"
      : "照片的去向已经写入这次 run 的卷宗。";
  const rememberedConsequence = keptBoth
    ? "这会成为一段单方保存的记忆：莱拉留下证据，阿拉什只记得她把两张都收走。"
    : splitPhotos
      ? "他们各自带走同一夜的一半，也共同记住照片被分开的时刻。"
      : "这次选择已经留下因果记录；谁保存了照片，谁就保存了这一夜的证据。";
  const choiceDisabled = !ready || !!pendingAction;

  const choosePhotoDestination = (targetId: "arash" | "leila", utterance: string) => {
    void handleAction({
      actionType: "give",
      utterance,
      tone: "gentle",
      targetId,
      evidenceIds: ["photo_pair"],
    });
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
      className="scene-photo-lab pb-14"
    >
      <ObserverCamera focuses={FOCUSES} defaultFocusId="wide" ariaLabel="地下放映室镜头">
        <SceneStage meta={sceneMeta} />
      </ObserverCamera>

      <div className="absolute top-28 sm:top-20 right-3 sm:right-6 z-40">
        <POVSwitcher />
      </div>

      <div className="absolute top-40 sm:top-28 right-3 sm:right-6 z-20 flex flex-col gap-2 max-w-xs">
        <StateFlux tone="warm" note="灯泡烘得空气发甜" />
      </div>

      <ObserverHint trigger="critical_moment" pov="arash" delayMs={8000} />
      <ObserverHint trigger="after_choice" pov="leila" delayMs={4000} />

      <div className="absolute bottom-32 left-0 right-0 z-20 px-3 sm:px-6">
        <div className="max-w-4xl mx-auto mb-3">
          <ObserverNarration text={currentNarration} typewriter />
        </div>
      </div>

      <div className="absolute bottom-32 right-6 z-20 w-80 max-h-72">
        <NPCReactions />
      </div>


      {showOtherActions && (
        <div
          className="absolute inset-x-3 sm:inset-x-6 bottom-20 z-40 max-h-[calc(100%-8rem)] overflow-y-auto glass-strong rounded-md p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Other actions"
          onKeyDown={(event) => { if (event.key === "Escape") setShowOtherActions(false); }}
        >
          <div className="flex items-center justify-between mb-3">
            <div>
              <p className="t-overline text-paper-100/50">其他行动</p>
              <p className="t-meta text-paper-200/60">调查环境，或使用结构化行为继续试探。</p>
            </div>
            <button type="button" className="action-btn" onClick={() => setShowOtherActions(false)} autoFocus>
              收起
            </button>
          </div>
          <div className="grid lg:grid-cols-[minmax(18rem,0.8fr)_minmax(30rem,1.4fr)] gap-4">
            <InvestigationPanel
              objects={sceneMeta.investigatableObjects}
              budget={sceneMeta.turnBudget.investigate ?? 3}
              onInvestigate={onInvestigate}
              disabled={!ready}
            />
            <ActionBar
              onAct={(params) => void handleAction(params)}
              contextActions={{
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
      )}

      <div className="absolute bottom-14 left-0 right-0 z-20 px-3 sm:px-6 pb-16">
        <div className="max-w-4xl mx-auto glass-strong rounded-md p-3 sm:p-4">
          <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-2 mb-3">
            <div>
              <p className="t-overline text-amber-glow">今夜只决定一件事</p>
              <h2 className="t-display text-xl text-paper-100">决定两张照片的去向</h2>
              <p className="t-narration text-sm text-paper-200/70">
                谁带走照片，谁就会替这一夜保存一份可以被记住的证据。
              </p>
            </div>
            <span className="t-meta text-paper-100/50">
              {runError ? "run 未就绪" : pendingAction ? "选择正在写入世界……" : ready ? "选择会立即生效" : "正在创建 run……"}
            </span>
          </div>
          {runError && (
            <div className="mb-3 flex items-center justify-between gap-3 border border-red-500/40 bg-red-500/10 rounded p-3">
              <p className="text-sm text-red-300">{runError}</p>
              <button type="button" className="action-btn border-amber-glow text-amber-glow" onClick={retryRun}>
                重试
              </button>
            </div>
          )}
          <div className="grid md:grid-cols-2 gap-3" role="group" aria-label="照片去向">
            <button
              type="button"
              data-testid="photo-choice-split"
              className="action-btn min-h-[72px] border-amber-glow text-left px-4"
              disabled={choiceDisabled}
              onClick={() => choosePhotoDestination("arash", "一人一张。你把一张夹进诗集，我带走另一张。")}
            >
              <span className="block t-overline text-amber-glow">A · 一人一张</span>
              <span className="block t-narration text-paper-100 mt-1">莱拉包里一张 · 阿拉什诗集里一张</span>
            </button>
            <button
              type="button"
              data-testid="photo-choice-keep-both"
              className="action-btn min-h-[72px] border-paper-100/30 text-left px-4"
              disabled={choiceDisabled}
              onClick={() => choosePhotoDestination("leila", "两张都先放在我这里。")}
            >
              <span className="block t-overline text-paper-200">B · 两张都留下</span>
              <span className="block t-narration text-paper-100 mt-1">两张都放进莱拉的包</span>
            </button>
          </div>
          <button
            type="button"
            className="mt-3 t-meta text-paper-100/60 underline underline-offset-4"
            onClick={() => setShowOtherActions((shown) => !shown)}
            aria-expanded={showOtherActions}
          >
            其他行动 · 调查 / 交谈 / 等待
          </button>
        </div>
      </div>

      <SceneStatusBar />

      {currentState === "scene_ended" && (
        <div className="absolute inset-0 z-40 flex items-center justify-center overflow-y-auto bg-ink-900/70 px-3 py-12 backdrop-blur">
          <div className="glass-strong w-full max-w-lg max-h-[calc(100vh-6rem)] overflow-y-auto p-5 sm:p-8 text-center" role="dialog" aria-modal="true" aria-label="Photo consequence" data-testid="photo-ending-consequence">
            <p className="t-overline text-amber-glow mb-2">选择已被世界记住</p>
            <h2 className="t-display text-2xl mb-3">{photoConsequence}</h2>
            {authoritativeEndingId && (
              <p className="t-meta text-paper-100/45 mb-3">结局记录 · {authoritativeEndingId}</p>
            )}
            <p className="t-narration text-paper-200 mb-2">
              {rememberedConsequence}
            </p>
            <p className="t-meta text-paper-100/50 mb-6">
              灯泡暗下来，放映机停住。此后如何回响，仍由你之后的行为决定。
            </p>
            <div className="flex flex-col sm:flex-row justify-center gap-2">
              <button className="action-btn" onClick={() => nav("/archive")} autoFocus>
                打开卷宗
              </button>
              <button
                className="action-btn border-amber-glow text-amber-glow"
                onClick={() => setJumping(true)}
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
        <div className="absolute inset-0 hidden sm:grid grid-cols-3 grid-rows-2 gap-4">
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
