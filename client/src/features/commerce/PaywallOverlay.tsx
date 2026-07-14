// =============================================================================
// 革命街没有尽头 · 付费墙浮动层（决策红线）
// -----------------------------------------------------------------------------
// 红线：付费入口只在「已结束 / 已解锁」状态出现——不在主线中段。
// 这个 overlay 仅在 currentState 是合法触发状态时显示。
// ============================================================================

import { useNavigate } from "react-router-dom";
import { useStore, canOpenPaywallInState } from "@/lib/store";

export function PaywallOverlay() {
  const open = useStore((s) => s.paywallOpen);
  const from = useStore((s) => s.paywallFrom);
  const close = useStore((s) => s.closePaywall);
  const currentState = useStore((s) => s.currentState);
  const nav = useNavigate();

  if (!open) return null;

  // 决策 4 红线：如果当前状态不允许弹付费墙，关闭并跳到主商店
  // （这是防御性代码——理论上 openPaywall 只能从合法状态触发）
  const allowed = canOpenPaywallInState(currentState);
  if (!allowed) {
    // 不渲染 overlay，但也不强制关闭（让上层逻辑决定）
    return null;
  }

  return (
    <div
      className="paywall-overlay"
      data-modal-open="true"
      role="dialog"
      aria-modal="true"
      aria-labelledby="paywall-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="glass-strong rounded-lg p-6 max-w-md w-full mx-4">
        <p className="t-overline text-amber-glow mb-1">提示</p>
        <h2 id="paywall-title" className="t-display text-2xl mb-3">
          这一段路还需要一点东西
        </h2>
        <p className="t-narration text-paper-200/80 text-sm mb-5">
          （你的免费样章已经走到头——下一步可以购买通行证、收藏版，或加点积分。）
        </p>
        <p className="t-meta text-paper-100/40 mb-6">
          触发状态：<span className="text-amber-glow">{from ?? "—"}</span>
        </p>
        <div className="flex gap-2">
          <button
            className="action-btn border-amber-glow text-amber-glow"
            onClick={() => {
              close();
              nav("/paywall");
            }}
          >
            打开商店
          </button>
          <button className="action-btn" onClick={close}>
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
