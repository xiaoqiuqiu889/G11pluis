// =============================================================================
// 革命街没有尽头 · 场景舞台容器
// -----------------------------------------------------------------------------
// 宽银幕 2.35:1 + 颗粒 + 暗角 + 状态栏
// 子组件：背景层（美术）、前景层（调查/行为/字幕）
// ============================================================================

import { ReactNode } from "react";

export interface CinematicFrameProps {
  children: ReactNode;
  /** 宽银幕美术背景 URL（或 mock 占位） */
  background?: string;
  /** 场景标题/年份（左上） */
  meta?: { year: string; location: string };
  /** 是否启用灯泡闪烁（地下放映室） */
  bulbFlicker?: boolean;
  className?: string;
}

export function CinematicFrame({
  children,
  background,
  meta,
  bulbFlicker = false,
  className = "",
}: CinematicFrameProps) {
  return (
    <div className={`cinematic-frame ${className}`}>
      {/* 背景层 */}
      {background ? (
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{ backgroundImage: `url(${background})` }}
          aria-hidden
        />
      ) : (
        <div
          className="absolute inset-0 bg-gradient-to-b from-ink-700 via-ink-800 to-ink-900"
          aria-hidden
        />
      )}

      {/* 暗色调遮罩（电影感） */}
      <div className="absolute inset-0 bg-gradient-to-b from-ink-900/60 via-ink-900/30 to-ink-900/80" aria-hidden />

      {/* 暗角 */}
      <div className="vignette" aria-hidden />

      {/* 颗粒 */}
      <div className="grain-overlay" aria-hidden />

      {/* 灯泡闪烁覆盖层（photo_lab 专用） */}
      {bulbFlicker && <div className="absolute inset-0 bulb-flicker pointer-events-none" aria-hidden />}

      {/* 状态栏：年份 + 地点（左上） */}
      {meta && (
        <div className="absolute top-12 left-6 z-20 max-w-md">
          <p className="t-overline text-amber-glow mb-1">{meta.year}</p>
          <p className="t-narration text-paper-200 text-sm">{meta.location}</p>
        </div>
      )}

      {/* 内容 */}
      <div className="relative z-10 min-h-screen h-full flex flex-col">{children}</div>
    </div>
  );
}
