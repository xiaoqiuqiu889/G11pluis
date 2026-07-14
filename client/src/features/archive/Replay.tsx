// =============================================================================
// 革命街没有尽头 · 重演 tab
// -----------------------------------------------------------------------------
// 决策 4：平行演算包 = 5 次额外重演（¥12）
// 重演点：基于 recentOutcomes 的 eventSequence 节点
// ============================================================================

import { Link } from "react-router-dom";
import { useStore } from "@/lib/store";
import { ArchiveEmpty, useArchiveData } from "./ArchivePage";

export function Replay() {
  const { outcomes, replayTickets } = useArchiveData();
  const consumeReplay = useStore((s) => s.consumeReplay);

  if (outcomes.length === 0) {
    return <ArchiveEmpty hint="还没有可以重演的事件节点。" />;
  }

  return (
    <div className="archive-section">
      <div className="flex items-center justify-between mb-4">
        <p className="t-narration text-paper-200/80 text-sm">
          （你看到的每一个 # 节点，都是你还能回去的分岔点——但回去要花平行演算。）
        </p>
        <span className="t-meta text-amber-glow">
          重演次数 <span className="t-num">{replayTickets}</span>
        </span>
      </div>

      <ul className="space-y-2" role="list">
        {outcomes.slice(0, 12).map((o) => (
          <li key={o.outcomeId} className="glass rounded p-3 flex items-center justify-between gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <span className="t-num text-amber-glow/80 text-xs">#{o.eventSequence}</span>
                <span className="t-meta text-paper-100/40">
                  {new Date(o.timestamp).toLocaleString("zh-CN", { hour12: false })}
                </span>
              </div>
              <p className="t-narration text-paper-100 text-sm truncate">
                {o.acceptedNpcAction.resolvedText}
              </p>
            </div>
            <button
              className="action-btn text-xs shrink-0"
              disabled={replayTickets <= 0}
              onClick={() => {
                if (consumeReplay()) {
                  // 触发重演（mock）
                  alert(`重演节点 #${o.eventSequence}（mock）`);
                }
              }}
            >
              重演这里
            </button>
          </li>
        ))}
      </ul>

      {replayTickets <= 0 && (
        <div className="mt-4 pov-hint text-center">
          <Link to="/paywall/parallel_ops" className="text-amber-glow">
            平行演算包 · ¥12 / 5 次
          </Link>
        </div>
      )}
    </div>
  );
}
