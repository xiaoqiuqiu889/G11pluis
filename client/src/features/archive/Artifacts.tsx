// =============================================================================
// 革命街没有尽头 · 物件当前归属 tab
// -----------------------------------------------------------------------------
// 显示本局物件（artifact）的当前归属（authoritative = Resolver 写入）
// 决策 2：解锁视角后，记忆账本的内容变化（这里只显示事实归属）
// ============================================================================

import { useStore } from "@/lib/store";
import { ArchiveEmpty, useArchiveData } from "./ArchivePage";

export function Artifacts() {
  const { progress } = useArchiveData();
  const povMode = useStore((s) => s.povMode);
  const unlockedPOVs = useStore((s) => s.unlockedPOVs);
  const sceneMeta = useStore((s) => s.sceneMeta);

  if (progress.artifactsHeld.length === 0) {
    return <ArchiveEmpty hint="把某样东西 give 出去或 give 给自己，就会在物件栏出现。" />;
  }

  // 决策 2：解锁视角后，记忆账本内容变化；这里只显示事实归属
  const inObserverMode = povMode === "observer" || !unlockedPOVs.includes(povMode);

  return (
    <div className="archive-section">
      <p className="t-meta text-amber-glow/60 mb-3">
        ✶ 物件的当前归属（事实层）{!inObserverMode ? " · 已切至角色视角，但本栏只显示事实。" : ""}
      </p>
      <ul className="space-y-2" role="list">
        {progress.artifactsHeld.map((id) => {
          const obj = sceneMeta?.investigatableObjects.find((o) => o.id === id);
          return (
            <li key={id} className="glass rounded p-4 flex items-center justify-between">
              <div>
                <h3 className="t-narration text-paper-100">{obj?.name ?? id}</h3>
                <p className="t-narration text-paper-200/70 text-sm">{obj?.description}</p>
              </div>
              <span className="t-num text-amber-glow/80 text-sm">持有</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
