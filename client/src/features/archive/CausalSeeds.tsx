// =============================================================================
// 革命街没有尽头 · 尚未闭合的因果 tab
// -----------------------------------------------------------------------------
// 决策 3：mandatory echo 必须显式登记
// 决策红线：not-yet-triggered 不能被说"你曾经 X"
// ============================================================================

import { useStore } from "@/lib/store";
import { ArchiveEmpty, useArchiveData } from "./ArchivePage";

export function CausalSeeds() {
  const { progress } = useArchiveData();
  const sceneMeta = useStore((s) => s.sceneMeta);

  const allSeeds = sceneMeta?.causalSeeds ?? [];
  const fired = progress.causalSeedsFired;
  const dormant = allSeeds.filter((s) => !fired.includes(s.id));
  const active = allSeeds.filter((s) => fired.includes(s.id));

  if (allSeeds.length === 0) {
    return <ArchiveEmpty hint="这一场暂时没有声明过的因果种子。" />;
  }

  return (
    <div className="archive-section space-y-6">
      <section>
        <h2 className="t-overline text-amber-glow mb-2">已触发</h2>
        {active.length === 0 ? (
          <p className="t-meta text-paper-100/40">（还没有。）</p>
        ) : (
          <ul className="space-y-2" role="list">
            {active.map((s) => (
              <li key={s.id} className="glass rounded p-4 border-amber-glow/40">
                <div className="flex items-center justify-between mb-1">
                  <span className="t-num text-amber-glow">{s.id}</span>
                  <span className="t-meta text-paper-100/40">active</span>
                </div>
                <p className="t-narration text-paper-100 text-sm">{s.description}</p>
                <ul className="mt-2 space-y-1">
                  {s.effects.map((e, i) => (
                    <li key={i} className="t-meta text-paper-200/60">
                      → {e}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="t-overline text-paper-100/40 mb-2">尚未闭合</h2>
        {dormant.length === 0 ? (
          <p className="t-meta text-paper-100/40">（这一栏是空的——可能本场不会有未闭合的种子。）</p>
        ) : (
          <ul className="space-y-2" role="list">
            {dormant.map((s) => (
              <li key={s.id} className="glass rounded p-4">
                <div className="flex items-center justify-between mb-1">
                  <span className="t-num text-paper-100/40">{s.id}</span>
                  <span className="t-meta text-paper-100/30">dormant</span>
                </div>
                <p className="t-narration text-paper-200/70 text-sm">{s.description}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
