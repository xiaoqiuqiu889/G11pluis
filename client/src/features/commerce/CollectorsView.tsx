// =============================================================================
// 革命街没有尽头 · 收藏版 · ¥48
// -----------------------------------------------------------------------------
// 决策 4：完整三场景 + 双视角 + 原声 + 私人终章 + 500 积分
// ============================================================================

import { useNavigate } from "react-router-dom";
import { useStore } from "@/lib/store";

export function CollectorsView() {
  const nav = useNavigate();
  const grantProduct = useStore((s) => s.grantProduct);
  const unlockPOV = useStore((s) => s.unlockPOV);

  const onBuy = () => {
    grantProduct("collectors", 500, 5);
    unlockPOV("leila");
    unlockPOV("arash");
    nav("/scene/photo_lab_2008");
  };

  return (
    <div className="max-w-3xl">
      <p className="t-overline text-amber-glow mb-2">收藏版</p>
      <h1 className="t-display text-4xl mb-2">¥48</h1>
      <p className="t-narration text-paper-200/80 mb-6">
        完整三场景 + 双视角（莱拉 + 阿拉什）+ Dastgah-e Shur 原声音轨 + 私人终章（根据本局时间线生成）+ 500 主调用积分 + 5 次平行演算。
      </p>
      <ul className="space-y-2 mb-8 text-paper-200">
        <li className="flex items-start gap-2">
          <span className="text-amber-glow">·</span>
          <span>完整三场景（无任何缩略）</span>
        </li>
        <li className="flex items-start gap-2">
          <span className="text-amber-glow">·</span>
          <span>解锁两个角色视角（莱拉 + 阿拉什）——记忆账本、情绪演出、NPC 内心独白全变</span>
        </li>
        <li className="flex items-start gap-2">
          <span className="text-amber-glow">·</span>
          <span>Dastgah-e Shur 原声音轨</span>
        </li>
        <li className="flex items-start gap-2">
          <span className="text-amber-glow">·</span>
          <span>私人终章（根据本局时间线生成，<strong>不是固定模板</strong>）</span>
        </li>
        <li className="flex items-start gap-2">
          <span className="text-amber-glow">·</span>
          <span>500 主调用积分</span>
        </li>
        <li className="flex items-start gap-2">
          <span className="text-amber-glow">·</span>
          <span>5 次平行演算</span>
        </li>
      </ul>
      <div className="flex gap-2">
        <button className="action-btn border-amber-glow text-amber-glow" onClick={onBuy}>
          升级收藏版
        </button>
        <button className="action-btn" onClick={() => nav("/paywall")}>
          返回
        </button>
      </div>
    </div>
  );
}
