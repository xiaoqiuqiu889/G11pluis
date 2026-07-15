// =============================================================================
// 革命街没有尽头 · 场景状态栏（描述性反馈）
// -----------------------------------------------------------------------------
// 决策红线：不显示精确数值（爱情值等）。
// 显示：调查剩余 / 行为剩余 / 积分 / 视角模式 / 降级等级。
// UP-20260715-040：商业化 UI 透明性 —— 状态栏 "?" 按钮 + 展开 panel
//   让玩家立刻知道"积分 30 是付费的" / "重演 1 是平行演算" / "P95 是延迟监控"
// ============================================================================

import { useState } from "react";
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
  const [legendOpen, setLegendOpen] = useState(false);

  const p95 = getP95Latency();

  return (
    <div
      className="g1n-scene-status fixed bottom-0 inset-x-0 z-30 glass-strong border-t border-paper-100/10 px-3 sm:px-4 py-2 flex items-center justify-between gap-3 overflow-hidden text-xs"
      role="status"
      aria-label="场景状态"
    >
      <div className="g1n-scene-status-primary flex min-w-0 items-center gap-3 overflow-hidden whitespace-nowrap">
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

      <div className="g1n-scene-status-secondary flex shrink-0 items-center gap-2 sm:gap-4 whitespace-nowrap">
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

        {/* UP-20260715-040：状态栏 "?" 按钮 — 立即可发现的图标 */}
        <button
          type="button"
          className="w-5 h-5 rounded-full border border-paper-100/30 text-paper-100/60 hover:border-amber-glow hover:text-amber-glow transition-colors flex items-center justify-center text-[10px] font-bold leading-none"
          onClick={() => setLegendOpen((v) => !v)}
          aria-expanded={legendOpen}
          aria-controls="status-legend"
          title="查看状态栏图例"
          data-testid="statusbar-legend-toggle"
        >
          ?
        </button>
      </div>

      {/* UP-20260715-040：状态栏图例 panel — 点击 "?" 展开 */}
      {legendOpen && (
        <div
          id="status-legend"
          className="absolute bottom-full right-4 mb-2 w-80 max-w-[90vw] glass-strong border border-paper-100/15 rounded-md p-4 text-xs space-y-2 z-40 shadow-xl"
          role="dialog"
          aria-label="状态栏图例"
        >
          <div className="flex items-center justify-between mb-2">
            <h4 className="t-overline text-amber-glow">状态栏图例</h4>
            <button
              type="button"
              className="text-paper-100/40 hover:text-paper-100 text-base leading-none"
              onClick={() => setLegendOpen(false)}
              aria-label="关闭"
            >
              ×
            </button>
          </div>
          <dl className="space-y-2">
            <div className="flex items-start gap-2">
              <dt className="t-num text-amber-glow shrink-0">积分</dt>
              <dd className="text-paper-200/80">
                <strong>主调用积分</strong>。决策 4 商业化档位：免费样章 30 积分；¥25=50 积分；¥48=120 积分。每次玩家行为扣 1 积分（NPC 反应 + Director + Resolver 一次完成）。
              </dd>
            </div>
            <div className="flex items-start gap-2">
              <dt className="t-num text-amber-glow shrink-0">重演</dt>
              <dd className="text-paper-200/80">
                <strong>平行演算次数</strong>。一个 run 结束后可基于同一存档 fork 分支，玩不同的选择。
              </dd>
            </div>
            <div className="flex items-start gap-2">
              <dt className="text-paper-100/40 shrink-0">P95</dt>
              <dd className="text-paper-200/80">
                <strong>关键交互响应延迟</strong>。决策 5 红线：&lt; 4s。超时会触发 L2/L3 降级（脚本接管 AI 反应）。
              </dd>
            </div>
            <div className="flex items-start gap-2">
              <dt className="text-paper-200/70 shrink-0">调查 X/3</dt>
              <dd className="text-paper-200/80">
                本场景已用 / 总预算的"调查"行为次数。
              </dd>
            </div>
            <div className="flex items-start gap-2">
              <dt className="text-paper-200/70 shrink-0">视角</dt>
              <dd className="text-paper-200/80">
                当前 POV（默认 = 旁观者）。切换到主角视角需付费解锁（决策 2 商业化档位 ¥3/视角）。
              </dd>
            </div>
            <div className="flex items-start gap-2">
              <dt className="text-amber-glow shrink-0">L1/L2/L3/L4</dt>
              <dd className="text-paper-200/80">
                <strong>降级等级</strong>。L1 = NPC 反应兜底；L2 = 跳过节拍；L3 = 脚本接管；L4 = 服务暂不可用。
              </dd>
            </div>
          </dl>
          <p className="t-meta text-paper-100/40 pt-2 border-t border-paper-100/10">
            完整商业化档位见 <Link to="/paywall" className="text-amber-glow hover:underline">商店</Link>。
          </p>
        </div>
      )}
    </div>
  );
}
