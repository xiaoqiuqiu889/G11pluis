// =============================================================================
// 革命街没有尽头 · 场景状态栏（描述性反馈）
// -----------------------------------------------------------------------------
// 决策红线：不显示精确数值（爱情值等）。
// 显示：调查剩余 / 行为剩余 / 积分 / 视角模式 / 降级等级。
// ============================================================================

import { Link } from "react-router-dom";
import { useStore } from "@/lib/store";
import { getP95Latency } from "@/lib/store";

export function SceneStatusBar() {
  const credits = useStore((s) => s.credits);
  const replayTickets = useStore((s) => s.replayTickets);
  const povMode = useStore((s) => s.povMode);
  const sceneProgress = useStore((s) => s.sceneProgress);
  const sceneMeta = useStore((s) => s.sceneMeta);
  const degradation = useStore((s) => s.degradationLevel);

  const p95 = getP95Latency();

  return (
    <div
      className="fixed bottom-0 inset-x-0 z-30 glass-strong border-t border-paper-100/10 px-4 py-2 flex items-center justify-between text-xs"
      role="status"
      aria-label="场景状态"
    >
      <div className="flex items-center gap-4">
        <Link to="/archive" className="t-meta text-paper-200/70 hover:text-amber-glow">
          卷宗
        </Link>
        <span className="text-paper-100/30">|</span>
        <span className="t-meta text-paper-200/70">
          调查 {sceneProgress.investigated.length} / {sceneMeta?.turnBudget.investigate ?? 3}
        </span>
        <span className="t-meta text-paper-200/70">
          视角 · {povMode === "observer" ? "旁观者" : povMode}
        </span>
        {degradation !== "none" && (
          <span className="t-meta text-amber-glow" aria-live="polite">
            · {degradation}
          </span>
        )}
      </div>

      <div className="flex items-center gap-4">
        {p95 > 0 && (
          <span className="t-meta text-paper-100/40" title="P95 关键交互响应（决策 5：< 4s）">
            P95 · <span className="t-num">{p95.toFixed(0)}ms</span>
          </span>
        )}
        <span className="t-meta text-paper-200/70" title="主调用积分（决策 4：¥12 / 150）">
          积分 <span className="t-num text-amber-glow">{credits}</span>
        </span>
        <span className="t-meta text-paper-200/70" title="平行演算次数">
          重演 <span className="t-num text-amber-glow">{replayTickets}</span>
        </span>
      </div>
    </div>
  );
}
