// =============================================================================
// 革命街没有尽头 · 降级徽章（决策 5：4 级降级链视觉反馈）
// -----------------------------------------------------------------------------
// 在屏幕右上角显示当前降级等级 + 原因
// ============================================================================

import { useStore } from "@/lib/store";

const LEVEL_LABEL: Record<string, string> = {
  none: "正常",
  L1: "L1 · 兜底台词",
  L2: "L2 · 跳过节拍",
  L3: "L3 · 脚本接管",
  L4: "L4 · 服务暂不可用",
};

const LEVEL_HINT: Record<string, string> = {
  none: "模型响应正常。",
  L1: "NPC 反应慢，用策划预设台词兜底；不影响状态。",
  L2: "导演超时，已跳过节拍校验，NPC 提案照常进入裁决。",
  L3: "本回合使用策划脚本推进，未调用模型。",
  L4: "网络中断或服务端不可用；本局结果已保存，可在网络恢复后重演。",
};

export function DegradationBadge() {
  const level = useStore((s) => s.degradationLevel);
  const lastError = useStore((s) => s.lastError);
  const network = useStore((s) => s.networkState);

  if (level === "none" && network !== "error") return null;

  return (
    <div
      className="degradation-badge"
      data-level={level}
      role="status"
      aria-live="polite"
      title={LEVEL_HINT[level] ?? ""}
    >
      <span className="t-num">{LEVEL_LABEL[level] ?? "?"}</span>
      {lastError && level === "L4" && (
        <div className="absolute top-full right-0 mt-2 w-64 glass-strong rounded p-3 text-[11px] leading-relaxed">
          <div className="text-vermillion-300 mb-1">提示</div>
          <div className="text-paper-200">{LEVEL_HINT[level]}</div>
          {lastError && <div className="mt-1 text-paper-100/50 t-meta">err: {lastError}</div>}
        </div>
      )}
    </div>
  );
}
