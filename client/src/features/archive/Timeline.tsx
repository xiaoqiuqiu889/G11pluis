// =============================================================================
// 革命街没有尽头 · 时间线 tab
// -----------------------------------------------------------------------------
// 显示本局已发生的事件（来自 recentOutcomes）
// ============================================================================

import { ArchiveEmpty, useArchiveData } from "./ArchivePage";

export function Timeline() {
  const { outcomes } = useArchiveData();

  if (outcomes.length === 0) {
    return <ArchiveEmpty hint="你还没有走过一个时间点。开始一局试试。" />;
  }

  return (
    <div className="archive-section">
      <ol className="relative border-l border-paper-100/10 ml-4 space-y-6">
        {outcomes.map((o) => (
          <li key={o.outcomeId} className="ml-6">
            <span
              className="absolute -left-1.5 w-3 h-3 rounded-full bg-amber-glow/60 border border-amber-glow"
              aria-hidden
            />
            <div className="flex items-center gap-2 mb-1">
              <span className="t-num text-amber-glow/80 text-xs">#{o.eventSequence}</span>
              <span className="t-meta text-paper-100/40">
                {new Date(o.timestamp).toLocaleString("zh-CN", { hour12: false })}
              </span>
            </div>
            <p className="t-narration text-paper-100 text-sm leading-relaxed">
              {o.acceptedNpcAction.resolvedText}
            </p>
            {o.firedCausalSeeds.length > 0 && (
              <p className="t-meta text-amber-glow/70 mt-1">
                ✶ 触发因果：{o.firedCausalSeeds.join("、")}
              </p>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
