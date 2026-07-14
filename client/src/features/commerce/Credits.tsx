// =============================================================================
// 革命街没有尽头 · 积分包 · ¥12 / 150 主调用
// -----------------------------------------------------------------------------
// 决策 5：单回合模型调用 ≤ 2 次；积分 = 主调用计数
// ============================================================================

import { useNavigate } from "react-router-dom";
import { useStore } from "@/lib/store";

export function Credits() {
  const nav = useNavigate();
  const grantProduct = useStore((s) => s.grantProduct);
  const credits = useStore((s) => s.credits);

  const onBuy = () => {
    grantProduct("credits", 150, 0);
    nav("/scene/photo_lab_2008");
  };

  return (
    <div className="max-w-3xl">
      <p className="t-overline text-amber-glow mb-2">积分包</p>
      <h1 className="t-display text-4xl mb-2">¥12</h1>
      <p className="t-narration text-paper-200/80 mb-6">
        150 次主调用积分。每个回合消耗 1 积分（决策 5：单回合 ≤ 2 次 LLM 调用）。
      </p>
      <p className="t-meta text-amber-glow/70 mb-6">
        当前剩余：<span className="t-num">{credits}</span>
      </p>
      <div className="flex gap-2">
        <button className="action-btn border-amber-glow text-amber-glow" onClick={onBuy}>
          购买 150 积分
        </button>
        <button className="action-btn" onClick={() => nav("/paywall")}>
          返回
        </button>
      </div>
    </div>
  );
}
