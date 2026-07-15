// =============================================================================
// 革命街没有尽头 · 调查面板（场景内）
// -----------------------------------------------------------------------------
// 5-7 个可调查对象；限调查 3-4 个（turn_budget.investigate）。
// 决策 1：调查行为 = investigate 行为类型的具体实例。
// ============================================================================

import { useStore } from "@/lib/store";
import type { InvestigatableObject } from "@/types/schemas";
import { useState } from "react";

export interface InvestigationPanelProps {
  objects: InvestigatableObject[];
  budget: number;
  onInvestigate: (obj: InvestigatableObject) => void;
  disabled?: boolean;
}

export function InvestigationPanel({ objects, budget, onInvestigate, disabled = false }: InvestigationPanelProps) {
  const investigated = useStore((s) => s.sceneProgress.investigated);
  const [hoverId, setHoverId] = useState<string | null>(null);

  const remaining = budget - investigated.length;
  const locked = remaining <= 0;

  return (
    <div
      className="w-full"
      role="region"
      aria-label="调查面板"
      aria-describedby="investigation-hint"
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="t-overline">调查 · INVESTIGATE</h3>
        <span className="t-meta text-paper-100/50">
          剩余 {Math.max(0, remaining)} / {budget}
        </span>
      </div>
      <p id="investigation-hint" className="t-narration text-sm text-paper-200/60 mb-3">
        （你看到——这些是这场里可以走近看的几样东西。）
      </p>

      <ul className="grid grid-cols-2 md:grid-cols-3 gap-2" role="list">
        {objects.map((obj) => {
          const isInvestigated = investigated.includes(obj.id);
          const isLocked = disabled || (locked && !isInvestigated);
          const isHover = hoverId === obj.id;
          return (
            <li key={obj.id}>
              <button
                type="button"
                className="investigation-chip w-full text-left"
                data-investigated={isInvestigated}
                data-locked={isLocked}
                disabled={isLocked}
                onClick={() => {
                  if (!isLocked) onInvestigate(obj);
                }}
                onMouseEnter={() => setHoverId(obj.id)}
                onMouseLeave={() => setHoverId(null)}
                onFocus={() => setHoverId(obj.id)}
                onBlur={() => setHoverId(null)}
                aria-label={`调查 ${obj.name}`}
                aria-describedby={`desc-${obj.id}`}
                aria-disabled={isLocked}
              >
                <div className="flex items-center gap-2">
                  <span className="t-meta text-amber-glow/70">
                    {String(objects.indexOf(obj) + 1).padStart(2, "0")}
                  </span>
                  <span className="t-narration text-sm text-paper-100">{obj.name}</span>
                </div>
                <p
                  id={`desc-${obj.id}`}
                  className={`text-xs text-paper-200/60 mt-1 transition-all ${
                    isHover || isInvestigated ? "max-h-20" : "max-h-0 overflow-hidden"
                  }`}
                >
                  {obj.description}
                </p>
                {obj.keywords.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {obj.keywords.slice(0, 3).map((k) => (
                      <span
                        key={k}
                        className="text-[10px] px-1.5 py-0.5 rounded-sm border border-paper-100/10 text-paper-100/40"
                      >
                        {k}
                      </span>
                    ))}
                  </div>
                )}
              </button>
            </li>
          );
        })}
      </ul>

      {locked && (
        <p className="mt-3 t-meta text-paper-100/40">
          （你已经看过了能看的几样——再往下，需要的不是眼睛。）
        </p>
      )}
    </div>
  );
}
