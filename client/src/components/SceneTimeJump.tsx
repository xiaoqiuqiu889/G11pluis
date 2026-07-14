// =============================================================================
// 革命街没有尽头 · 时间跳转过渡（场景间 / 场景结束）
// -----------------------------------------------------------------------------
// - 旧胶片烧灼 + 场景年份浮现
// - 完成后回调 onDone
// - 减动态 fallback
// ============================================================================

import { useEffect, useState } from "react";
import { useStore } from "@/lib/store";

export interface SceneTimeJumpProps {
  /** 目标年份（"2008 · 夏" / "2011 · 秋" / "2024 · 秋"） */
  year: string;
  /** 副标题（"革命街地下放映室"） */
  subtitle?: string;
  /** 持续时间 ms，默认 2400 */
  durationMs?: number;
  /** 完成后回调 */
  onDone: () => void;
}

export function SceneTimeJump({ year, subtitle, durationMs = 2400, onDone }: SceneTimeJumpProps) {
  const reducedMotion = useStore((s) => s.reducedMotion);
  const [showBurnout, setShowBurnout] = useState(true);

  useEffect(() => {
    const t1 = window.setTimeout(() => setShowBurnout(false), reducedMotion ? 200 : 1200);
    const t2 = window.setTimeout(() => onDone(), reducedMotion ? 400 : durationMs);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, [durationMs, onDone, reducedMotion]);

  return (
    <>
      {showBurnout && <div className="scene-burnout" aria-hidden />}
      <div className="scene-transition" role="status" aria-live="polite">
        <div className="text-center">
          <p className="scene-transition__year t-italic">{year}</p>
          {subtitle && (
            <p className="mt-2 t-narration text-paper-200 text-base tracking-widest">{subtitle}</p>
          )}
        </div>
      </div>
    </>
  );
}
