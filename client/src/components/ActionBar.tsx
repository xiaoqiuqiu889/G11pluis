// =============================================================================
// 革命街没有尽头 · 行为栏（12 种结构化行为 + 自然语言输入）
// -----------------------------------------------------------------------------
// 决策 1：每个场景必须支持 ≥ 6 种结构化行为。
// 决策红线：不显示「自由聊天」——所有 AI 输出走叙事合同 + 提案制。
// 全部 12 种来自 player_action.schema.json。
// ============================================================================

import { useState } from "react";
import type { ActionType, Tone } from "@/types/schemas";
import { useStore } from "@/lib/store";

const ACTIONS: Array<{ type: ActionType; label: string; hint: string; tags?: string[] }> = [
  { type: "investigate", label: "调查", hint: "走近看一样东西", tags: ["scan"] },
  { type: "reveal", label: "揭露", hint: "让一件事浮出水面" },
  { type: "conceal", label: "隐藏", hint: "把一句话/动作收回去" },
  { type: "question", label: "询问", hint: "向对方发问", tags: ["dialogue"] },
  { type: "confront", label: "直面", hint: "承认一段悬而未决的关系" },
  { type: "comfort", label: "安抚", hint: "把对方的紧张接住", tags: ["dialogue"] },
  { type: "give", label: "给出", hint: "把一样东西/一句话交出" },
  { type: "destroy", label: "销毁", hint: "把冲印废片/未寄的字条处理掉" },
  { type: "promise", label: "承诺", hint: "在某物上许下不写日期的约定" },
  { type: "wait", label: "等待", hint: "让一段沉默持续三秒以上" },
  { type: "leave", label: "离开", hint: "先走出场景" },
  { type: "silence", label: "沉默", hint: "把已经成型的句子咽回去", tags: ["dialogue"] },
];

const TONE_OPTIONS: Array<{ id: Tone; label: string }> = [
  { id: "neutral", label: "中" },
  { id: "hesitant", label: "犹豫" },
  { id: "firm", label: "稳" },
  { id: "gentle", label: "轻" },
  { id: "sad", label: "重" },
  { id: "angry", label: "重·锋" },
  { id: "playful", label: "玩笑" },
];

export interface ActionBarProps {
  onAct: (params: {
    actionType: ActionType;
    utterance: string;
    tone: Tone;
    targetId?: string | null;
    evidenceIds?: string[];
  }) => void;
  disabled?: boolean;
  contextActions?: Partial<Record<ActionType, { label: string; targetId: string }>>;
}

export function ActionBar({ onAct, disabled, contextActions }: ActionBarProps) {
  const [picked, setPicked] = useState<ActionType | null>(null);
  const [utterance, setUtterance] = useState("");
  const [tone, setTone] = useState<Tone>("neutral");
  const pending = useStore((s) => s.pendingAction);
  const isPending = !!pending;

  const submit = () => {
    if (!picked) return;
    const ctx = contextActions?.[picked];
    onAct({
      actionType: picked,
      utterance: utterance.trim().slice(0, 500),
      tone,
      targetId: ctx?.targetId,
    });
    setUtterance("");
    setPicked(null);
  };

  return (
    <div
      className="glass rounded-md p-4"
      role="region"
      aria-label="行为栏"
      aria-disabled={disabled || isPending}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="t-overline">行为 · ACT</h3>
        <span className="t-meta text-paper-100/50">
          {isPending ? "正在回应……" : "选择一种动作"}
        </span>
      </div>

      {/* 12 种行为按钮 */}
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2" role="group" aria-label="12 种结构化行为">
        {ACTIONS.map((a) => (
          <button
            key={a.type}
            type="button"
            className="action-btn"
            data-type={a.type}
            data-active={picked === a.type}
            disabled={disabled || isPending}
            onClick={() => setPicked(a.type)}
            title={a.hint}
            aria-pressed={picked === a.type}
          >
            <div className="text-base">{a.label}</div>
            <div className="text-[10px] text-paper-100/50 mt-0.5 leading-tight">{a.hint}</div>
          </button>
        ))}
      </div>

      {/* 选中行为后：自然语言 + tone */}
      {picked && (
        <div className="mt-4 space-y-3 animate-slide-up">
          <div>
            <label htmlFor="utterance" className="t-overline block mb-1.5">
              自然语言（可选，500 字内）
            </label>
            <textarea
              id="utterance"
              className="w-full bg-ink-800/60 border border-paper-100/10 rounded px-3 py-2 text-sm text-paper-100 resize-none focus:border-amber-glow"
              rows={2}
              maxLength={500}
              placeholder="说点什么，或者留空——NPC 仍会按合同回应。"
              value={utterance}
              onChange={(e) => setUtterance(e.target.value)}
              disabled={isPending}
            />
            <div className="flex items-center justify-between mt-1">
              <span className="t-meta text-paper-100/40">{utterance.length} / 500</span>
            </div>
          </div>

          <div>
            <span className="t-overline block mb-1.5">语气</span>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="语气">
              {TONE_OPTIONS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className={`px-2.5 py-1 text-xs rounded border transition-colors min-h-[32px] ${
                    tone === t.id
                      ? "border-amber-glow text-amber-glow bg-amber-glow/10"
                      : "border-paper-100/10 text-paper-200/70 hover:border-paper-100/30"
                  }`}
                  onClick={() => setTone(t.id)}
                  role="radio"
                  aria-checked={tone === t.id}
                  disabled={isPending}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              className="action-btn border-amber-glow text-amber-glow hover:bg-amber-glow/10"
              onClick={submit}
              disabled={isPending}
            >
              提交 · {ACTIONS.find((a) => a.type === picked)?.label}
            </button>
            <button
              type="button"
              className="action-btn"
              onClick={() => {
                setPicked(null);
                setUtterance("");
              }}
              disabled={isPending}
            >
              取消
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
