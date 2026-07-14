// =============================================================================
// 革命街没有尽头 · 视角切换器（决策 2）
// -----------------------------------------------------------------------------
// 默认 = 旁观者；切到角色视角需要付费解锁。
// 视觉提示：未解锁的视角是"暗的"，但能"听见"一点点（暗示存在）。
// ============================================================================

import { useStore } from "@/lib/store";
import type { POVMode } from "@/lib/store";

const POV_META: Array<{ id: POVMode; name: string; desc: string }> = [
  { id: "observer", name: "旁观者", desc: "默认视角" },
  { id: "leila", name: "莱拉", desc: "摄影 / 诗 / 物" },
  { id: "arash", name: "阿拉什", desc: "工具 / 声音 / 修理" },
  { id: "kamran", name: "卡姆兰", desc: "另一时区" },
  { id: "maryam", name: "玛丽亚姆", desc: "天文台坐标" },
];

export function POVSwitcher() {
  const povMode = useStore((s) => s.povMode);
  const unlockedPOVs = useStore((s) => s.unlockedPOVs);
  const setPOV = useStore((s) => s.setPOV);
  const openPaywall = useStore((s) => s.openPaywall);

  return (
    <div
      className="flex items-center gap-1 glass rounded-full px-1.5 py-1"
      role="radiogroup"
      aria-label="叙事视角"
    >
      {POV_META.map((m) => {
        const isActive = m.id === povMode;
        const isUnlocked = m.id === "observer" || unlockedPOVs.includes(m.id);
        return (
          <button
            key={m.id}
            role="radio"
            aria-checked={isActive}
            aria-disabled={!isUnlocked}
            disabled={!isUnlocked}
            onClick={() => {
              if (!isUnlocked) {
                openPaywall("pov_unlock" as unknown as SceneId);
                return;
              }
              setPOV(m.id);
            }}
            className={`px-3 py-1.5 text-xs rounded-full transition-all min-h-[32px] ${
              isActive
                ? "bg-amber-glow text-ink-900"
                : isUnlocked
                  ? "text-paper-200/80 hover:text-paper-100"
                  : "text-paper-100/25 cursor-not-allowed"
            }`}
            title={isUnlocked ? m.desc : `未解锁 — ¥3 / 段（决策 2：付费解锁）`}
          >
            {m.name}
            {!isUnlocked && <span className="ml-1 text-amber-glow/60">·₪</span>}
          </button>
        );
      })}
    </div>
  );
}

// 引入 SceneId 用于 openPaywall 类型对齐
type SceneId = "photo_lab_2008" | "farewell_2011" | "reunion_2024";
