// =============================================================================
// 革命街没有尽头 · NPC 反应列表（流式 / 打字机）
// -----------------------------------------------------------------------------
// 显示当前场景的 NPC 反应，按时间顺序。
// 打字机：每个反应逐字显示；可被新反应中断。
// ============================================================================

import { useEffect, useRef, useState } from "react";
import type { SpeechIntent } from "@/types/schemas";
import { useStore } from "@/lib/store";

const INTENT_LABEL: Record<SpeechIntent, string> = {
  seek_confirmation: "求证",
  defend: "辩护",
  accuse: "质问",
  comfort: "安抚",
  question: "反问",
  admit: "承认",
  deflect: "回避",
  threaten: "威胁",
  plead: "恳求",
  reassure: "安慰",
  taunt: "讥讽",
  reveal_truth: "说出",
  conceal_truth: "藏起",
  remain_silent: "（沉默）",
};

export function NPCReactions() {
  const reactions = useStore((s) => s.sceneProgress.npcReactions);
  const last = reactions[reactions.length - 1];

  return (
    <div
      className="space-y-1.5 max-h-72 overflow-y-auto pr-2"
      role="log"
      aria-live="polite"
      aria-label="NPC 反应"
    >
      {reactions.length === 0 ? (
        <p className="t-meta text-paper-100/30 italic">（这一场暂时还没有人开口。）</p>
      ) : (
        reactions.map((r, i) => (
          <NPCLine key={`${r.timestamp}-${i}`} {...r} isLatest={i === reactions.length - 1} />
        ))
      )}
    </div>
  );
}

function NPCLine({
  characterId,
  text,
  intent,
  timestamp,
  isLatest,
}: {
  characterId: string;
  text: string;
  intent: string;
  timestamp: string;
  isLatest: boolean;
}) {
  const reducedMotion = useStore((s) => s.reducedMotion);
  const [displayed, setDisplayed] = useState(isLatest && !reducedMotion ? "" : text);
  const [done, setDone] = useState(!isLatest || reducedMotion);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isLatest || reducedMotion) {
      setDisplayed(text);
      setDone(true);
      return;
    }
    setDisplayed("");
    setDone(false);
    let i = 0;
    const t = window.setInterval(() => {
      i += 1;
      if (i >= text.length) {
        setDisplayed(text);
        setDone(true);
        window.clearInterval(t);
      } else {
        setDisplayed(text.slice(0, i));
      }
    }, 28);
    return () => window.clearInterval(t);
  }, [text, isLatest, reducedMotion]);

  useEffect(() => {
    if (ref.current && isLatest) {
      ref.current.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "end" });
    }
  }, [displayed, isLatest, reducedMotion]);

  return (
    <div ref={ref} className="npc-line" data-intent={intent}>
      <div className="flex items-center justify-between mb-1">
        <span className="t-overline text-amber-glow/80">{characterId}</span>
        <span className="t-meta text-paper-100/30">
          {INTENT_LABEL[intent as SpeechIntent] ?? intent}
        </span>
      </div>
      <p className={`t-narration text-paper-100 text-sm leading-relaxed ${done ? "" : "typewriter"}`}>
        {displayed || (isLatest && reducedMotion ? text : " ")}
      </p>
    </div>
  );
}
