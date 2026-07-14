// =============================================================================
// 革命街没有尽头 · 证据 tab
// -----------------------------------------------------------------------------
// 显示本局已发现的 evidence / artifact
// ============================================================================

import { useStore } from "@/lib/store";
import { ArchiveEmpty, useArchiveData } from "./ArchivePage";

export function Evidence() {
  const { progress } = useArchiveData();
  const sceneMeta = useStore((s) => s.sceneMeta);
  const investigated = progress.investigated;

  if (investigated.length === 0) {
    return <ArchiveEmpty hint="走几个调查点就能在证据栏里看到这里。" />;
  }

  const items = sceneMeta?.investigatableObjects.filter((o) => investigated.includes(o.id)) ?? [];

  return (
    <div className="archive-section">
      <ul className="grid sm:grid-cols-2 gap-3" role="list">
        {items.map((it) => (
          <li key={it.id} className="glass rounded p-4">
            <div className="flex items-center justify-between mb-1">
              <h3 className="t-narration text-paper-100">{it.name}</h3>
              <span className="t-meta text-amber-glow/70">{it.iconKey ?? "—"}</span>
            </div>
            <p className="t-narration text-paper-200/70 text-sm">{it.description}</p>
            {it.leadsTo.length > 0 && (
              <p className="t-meta text-paper-100/40 mt-2">→ 指向：{it.leadsTo.join("、")}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
