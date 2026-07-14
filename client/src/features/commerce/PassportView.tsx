// =============================================================================
// 革命街没有尽头 · 案件通行证 · ¥25
// -----------------------------------------------------------------------------
// 决策 4：纵切片完整三场景 + 2 次重演 + 200 积分
// ============================================================================

import { useNavigate } from "react-router-dom";
import { useStore } from "@/lib/store";

export function PassportView() {
  const nav = useNavigate();
  const grantProduct = useStore((s) => s.grantProduct);

  const onBuy = () => {
    grantProduct("passport", 200, 2);
    nav("/scene/photo_lab_2008");
  };

  return (
    <div className="max-w-3xl">
      <p className="t-overline text-amber-glow mb-2">案件通行证</p>
      <h1 className="t-display text-4xl mb-2">¥25</h1>
      <p className="t-narration text-paper-200/80 mb-6">
        一份纵切片的完整三场景、两次重演、200 主调用积分。足够你从 2008 夏走到 2024 秋，把所有因果种子走一遍。
      </p>
      <ul className="space-y-2 mb-8 text-paper-200">
        <li className="flex items-start gap-2">
          <span className="text-amber-glow">·</span>
          <span>完整三场景（不受 5 分钟缩略限制）</span>
        </li>
        <li className="flex items-start gap-2">
          <span className="text-amber-glow">·</span>
          <span>2 次平行演算（重演）</span>
        </li>
        <li className="flex items-start gap-2">
          <span className="text-amber-glow">·</span>
          <span>200 主调用积分</span>
        </li>
        <li className="flex items-start gap-2">
          <span className="text-amber-glow">·</span>
          <span>基础卷宗（记忆账本 / 因果种子）</span>
        </li>
      </ul>
      <div className="flex gap-2">
        <button
          className="action-btn border-amber-glow text-amber-glow"
          onClick={onBuy}
        >
          购买并进入
        </button>
        <button className="action-btn" onClick={() => nav("/paywall")}>
          返回
        </button>
      </div>
      <p className="t-meta text-paper-100/30 mt-6">
        （这是 mock 流程——不会真扣款。真集成时由后端校验订单。）
      </p>
    </div>
  );
}
