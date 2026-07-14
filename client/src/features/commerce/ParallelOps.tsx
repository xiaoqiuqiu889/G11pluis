// =============================================================================
// 革命街没有尽头 · 平行演算包 · ¥12 / 5 次
// -----------------------------------------------------------------------------
// 决策 4：用于在事件节点上回到从前，重做一次选择
// ============================================================================

import { useNavigate } from "react-router-dom";
import { useStore } from "@/lib/store";

export function ParallelOps() {
  const nav = useNavigate();
  const grantProduct = useStore((s) => s.grantProduct);
  const replayTickets = useStore((s) => s.replayTickets);

  const onBuy = () => {
    grantProduct("parallel_ops", 0, 5);
    nav("/archive/replay");
  };

  return (
    <div className="max-w-3xl">
      <p className="t-overline text-amber-glow mb-2">平行演算包</p>
      <h1 className="t-display text-4xl mb-2">¥12</h1>
      <p className="t-narration text-paper-200/80 mb-6">
        5 次重演次数，回到任何已经走过的事件节点，重新做一次选择。
      </p>
      <p className="t-meta text-amber-glow/70 mb-6">
        当前剩余：<span className="t-num">{replayTickets}</span>
      </p>
      <div className="flex gap-2">
        <button className="action-btn border-amber-glow text-amber-glow" onClick={onBuy}>
          购买 5 次重演
        </button>
        <button className="action-btn" onClick={() => nav("/paywall")}>
          返回
        </button>
      </div>
    </div>
  );
}
