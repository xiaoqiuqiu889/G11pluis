// =============================================================================
// 革命街没有尽头 · 已形成记忆 tab
// -----------------------------------------------------------------------------
// 决策 2：解锁视角后，记忆账本的内容变化（这是关键差异点）
// ============================================================================

import { useStore } from "@/lib/store";
import { ArchiveEmpty, useArchiveData } from "./ArchivePage";

export function Memories() {
  const { progress } = useArchiveData();
  const povMode = useStore((s) => s.povMode);
  const unlockedPOVs = useStore((s) => s.unlockedPOVs);

  // 旁观者视角：只有公开记忆
  // 角色视角：公开 + 角色独白
  const isCharacterView = povMode !== "observer" && unlockedPOVs.includes(povMode);

  // Mock：把 NPC 反应视作公开记忆；如切到角色视角，加入"角色独白"
  const publicMemories = progress.npcReactions.map((r) => ({
    id: `${r.timestamp}-${r.characterId}`,
    summary: r.text,
    who: r.characterId,
    weight: "中性",
  }));

  const privateMonologue = isCharacterView
    ? [
        {
          id: "private-1",
          summary:
            povMode === "leila"
              ? "（她把照片分给他的时候，心里其实不打算让这一夜就结束——但她没说。）"
              : "（他接过那张照片的时候，手在抖——但他没说。）",
          who: povMode,
          weight: "重",
        },
      ]
    : [];

  const all = [...publicMemories, ...privateMonologue];

  if (all.length === 0) {
    return <ArchiveEmpty hint="还没有形成可记的事——先走一个回合。" />;
  }

  return (
    <div className="archive-section space-y-4">
      {!isCharacterView && (
        <div className="pov-hint">
          <span className="t-italic">
            （如果你是 <em>{povMode === "observer" ? "莱拉" : povMode}</em>，这栏会多一段没有说出口的独白。视角切换是付费解锁——¥3 / 段，或包含在 ¥48 收藏版里。）
          </span>
        </div>
      )}
      <ul className="space-y-2" role="list">
        {all.map((m) => (
          <li
            key={m.id}
            className={`glass rounded p-4 ${m.weight === "重" ? "border-amber-glow/40" : ""}`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="t-meta text-amber-glow/80">{m.who}</span>
              <span className="t-meta text-paper-100/40">{m.weight}</span>
            </div>
            <p className="t-narration text-paper-100 text-sm">{m.summary}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
