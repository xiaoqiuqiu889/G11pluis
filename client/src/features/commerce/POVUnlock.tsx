// =============================================================================
// 革命街没有尽头 · 额外人物视角 · ¥3 / 段
// -----------------------------------------------------------------------------
// 决策 2：解锁视角后，不是换 UI，是换叙事——记忆账本、情绪演出、NPC 内心独白全变。
// ============================================================================

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "@/lib/store";
import type { POVMode } from "@/lib/store";

const OPTIONS: Array<{ id: POVMode; name: string; price: number; desc: string }> = [
  { id: "leila", name: "莱拉", price: 3, desc: "她的诗、她的物、她没说出口的那一句" },
  { id: "arash", name: "阿拉什", price: 3, desc: "他的工具、他的声音、他的合工具盒盖那一下" },
  { id: "kamran", name: "卡姆兰", price: 3, desc: "另一时区、另一段尚未打开的叙事" },
  { id: "maryam", name: "玛丽亚姆", price: 3, desc: "天文台坐标；屋顶与流星观测" },
];

export function POVUnlock() {
  const nav = useNavigate();
  const unlockPOV = useStore((s) => s.unlockPOV);
  const setPOV = useStore((s) => s.setPOV);
  const unlocked = useStore((s) => s.unlockedPOVs);
  const [selected, setSelected] = useState<POVMode>("leila");

  const onBuy = () => {
    unlockPOV(selected);
    setPOV(selected);
    nav("/archive/memories");
  };

  return (
    <div className="max-w-3xl">
      <p className="t-overline text-amber-glow mb-2">额外人物视角</p>
      <h1 className="t-display text-4xl mb-2">¥3 / 段</h1>
      <p className="t-narration text-paper-200/80 mb-6">
        视角解锁后，<strong>不是换 UI</strong>，是换叙事——记忆账本、情绪演出、NPC 内心独白全变。已经在收藏版里的视角无需再买。
      </p>

      <ul className="space-y-2 mb-6" role="radiogroup" aria-label="选择视角">
        {OPTIONS.map((o) => {
          const isOwned = unlocked.includes(o.id);
          return (
            <li key={o.id}>
              <label
                className={`flex items-center gap-3 p-3 rounded border cursor-pointer ${
                  selected === o.id
                    ? "border-amber-glow bg-amber-glow/10"
                    : "border-paper-100/10 hover:border-paper-100/30"
                }`}
              >
                <input
                  type="radio"
                  name="pov"
                  value={o.id}
                  checked={selected === o.id}
                  onChange={() => setSelected(o.id)}
                  className="accent-amber-glow"
                  aria-label={o.name}
                />
                <div className="flex-1">
                  <div className="t-narration text-paper-100">{o.name}</div>
                  <div className="t-meta text-paper-100/50 text-xs">{o.desc}</div>
                </div>
                {isOwned ? (
                  <span className="t-meta text-amber-glow">已拥有</span>
                ) : (
                  <span className="t-num text-amber-glow">¥{o.price}</span>
                )}
              </label>
            </li>
          );
        })}
      </ul>

      <div className="flex gap-2">
        <button
          className="action-btn border-amber-glow text-amber-glow"
          onClick={onBuy}
          disabled={unlocked.includes(selected)}
        >
          {unlocked.includes(selected) ? "已拥有" : "解锁并切换"}
        </button>
        <button className="action-btn" onClick={() => nav("/paywall")}>
          返回
        </button>
      </div>
    </div>
  );
}
