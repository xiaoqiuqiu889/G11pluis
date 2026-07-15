// =============================================================================
// 革命街没有尽头 · 旁观者旁白组件（决策 2 核心）
// -----------------------------------------------------------------------------
// 旁白用"你看到了 X"保持距离感；不显示精确数值；
// 状态反馈用描述性语言（"他的手在杯沿停了一下"）。
// 视角切换 = 付费解锁；未解锁的视角只暗示存在。
// ============================================================================

import { useEffect, useState } from "react";
import { useStore } from "@/lib/store";

export interface ObserverNarrationProps {
  /** 旁白正文（描述性，"你看到了 X"） */
  text: string;
  /** 是否启用打字机效果 */
  typewriter?: boolean;
  /** 打字速度（ms/字） */
  speedMs?: number;
  /** 完成后回调 */
  onComplete?: () => void;
  /** 自定义类名 */
  className?: string;
}

const TONE_PREFIX: Record<string, string> = {
  // 不同氛围下的前缀
  neutral: "你看到了",
  warm: "你看到了",
  cold: "你看见了",
  dark: "你隐约看到",
};

export function ObserverNarration({
  text,
  typewriter = true,
  speedMs = 36,
  onComplete,
  className = "",
}: ObserverNarrationProps) {
  const reducedMotion = useStore((s) => s.reducedMotion);
  const [displayed, setDisplayed] = useState(typewriter && !reducedMotion ? "" : text);
  const [done, setDone] = useState(!typewriter || reducedMotion);

  useEffect(() => {
    if (!typewriter || reducedMotion) {
      setDisplayed(text);
      setDone(true);
      onComplete?.();
      return;
    }
    setDisplayed("");
    setDone(false);
    let i = 0;
    const interval = window.setInterval(() => {
      i += 1;
      if (i >= text.length) {
        setDisplayed(text);
        setDone(true);
        window.clearInterval(interval);
        onComplete?.();
      } else {
        setDisplayed(text.slice(0, i));
      }
    }, speedMs);
    return () => window.clearInterval(interval);
  }, [text, typewriter, speedMs, reducedMotion, onComplete]);

  // 拆分"你看到了"前缀 + 正文
  const prefix = pickPrefix(text);
  const body = text.startsWith(prefix) ? text.slice(prefix.length) : text;

  return (
    <div
      className={`t-observer ${className}`}
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <span className="text-amber-glow font-medium">{prefix}</span>
      <span className={done ? "" : "typewriter"}>{body}</span>
    </div>
  );
}

function pickPrefix(text: string): string {
  if (text.startsWith("你看到了")) return "你看到了";
  if (text.startsWith("你看见了")) return "你看见了";
  if (text.startsWith("你隐约")) return "你隐约看到";
  return TONE_PREFIX.neutral;
}

// =============================================================================
// 描述性状态反馈（不显示精确数值，决策红线）
// =============================================================================

export type EmotionalTone = "calm" | "tense" | "warm" | "strained" | "distant" | "intimate" | "cold" | "bitter";

export function StateFlux({ tone, note }: { tone: EmotionalTone; note?: string }) {
  const label = describeTone(tone);
  return (
    <span className="state-flux" data-tone={tone} aria-label={`气氛：${label}`}>
      <span>{label}</span>
      {note && <span className="text-paper-100/50 ml-2 text-xs">— {note}</span>}
    </span>
  );
}

function describeTone(t: EmotionalTone): string {
  switch (t) {
    case "calm":
      return "静";
    case "tense":
      return "紧绷";
    case "warm":
      return "有一点暖";
    case "strained":
      return "有点撑";
    case "distant":
      return "远";
    case "intimate":
      return "近";
    case "cold":
      return "冷";
    case "bitter":
      return "苦涩";
  }
  return "";
}

// =============================================================================
// 描述性时间 / 距离 / 强度（"5 分钟前" 而不是 "5:32"）
// =============================================================================

export function RelativeTime({ anchor, current }: { anchor: number; current: number }) {
  const diff = Math.max(0, current - anchor);
  if (diff < 60_000) return <span>刚才</span>;
  if (diff < 3_600_000) return <span>{Math.floor(diff / 60_000)} 分钟前</span>;
  return <span>{Math.floor(diff / 3_600_000)} 小时前</span>;
}

export function TenseNote({ children }: { children: React.ReactNode }) {
  return <span className="t-meta text-amber-glow">{children}</span>;
}
