// =============================================================================
// 革命街没有尽头 · 设置页
// -----------------------------------------------------------------------------
// 声音、字幕速度、减动态、语言
// ============================================================================

import { useStore } from "@/lib/store";
import { audioEngine } from "@/audio/AudioEngine";

export default function SettingsPage() {
  const audioEnabled = useStore((s) => s.audioEnabled);
  const audioVolume = useStore((s) => s.audioVolume);
  const textSpeed = useStore((s) => s.textSpeed);
  const reducedMotion = useStore((s) => s.reducedMotion);
  const language = useStore((s) => s.language);

  const setAudio = useStore((s) => s.setAudio);
  const setVolume = useStore((s) => s.setVolume);
  const setTextSpeed = useStore((s) => s.setTextSpeed);
  const setLanguage = useStore((s) => s.setLanguage);

  return (
    <div className="min-h-screen pt-14 pb-12 px-4 md:px-8 max-w-3xl mx-auto">
      <header className="mb-8">
        <p className="t-overline text-amber-glow mb-2">设置</p>
        <h1 className="t-display text-3xl md:text-4xl">偏好</h1>
      </header>

      <Section title="声音" desc="默认静音。需要用户手势启动。">
        <Row
          label="启用声音"
          help="包含 Dastgah-e Shur 风格的环境声 / 主题 / 母题。"
        >
          <Toggle
            on={audioEnabled}
            onChange={(b) => {
              setAudio(b);
              if (b) void audioEngine.start("prologue");
            }}
          />
        </Row>
        <Row label="音量">
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={audioVolume}
            onChange={(e) => setVolume(parseFloat(e.target.value))}
            className="accent-amber-glow"
            disabled={!audioEnabled}
            aria-label="音量"
          />
        </Row>
      </Section>

      <Section title="字幕" desc="NPC 反应的打字机速度（决策红线：不显示精确数值）。">
        <Row label="打字速度">
          <div className="flex gap-1">
            {(["slow", "normal", "fast"] as const).map((s) => (
              <button
                key={s}
                className={`action-btn text-xs ${
                  textSpeed === s ? "border-amber-glow text-amber-glow" : ""
                }`}
                onClick={() => setTextSpeed(s)}
                aria-pressed={textSpeed === s}
              >
                {s === "slow" ? "慢" : s === "normal" ? "中" : "快"}
              </button>
            ))}
          </div>
        </Row>
      </Section>

      <Section title="可访问性" desc="遵循系统偏好。">
        <Row label="减动态" help="系统层 prefers-reduced-motion。开启后颗粒 / 闪烁 / 缓动会减弱。">
          <span className="t-meta text-paper-100/50">
            {reducedMotion ? "已启用" : "跟随系统"}
          </span>
        </Row>
      </Section>

      <Section title="语言" desc="中文为主，英文作为元数据。">
        <Row label="界面语言">
          <div className="flex gap-1">
            {(["zh-CN", "en"] as const).map((l) => (
              <button
                key={l}
                className={`action-btn text-xs ${
                  language === l ? "border-amber-glow text-amber-glow" : ""
                }`}
                onClick={() => setLanguage(l)}
                aria-pressed={language === l}
              >
                {l === "zh-CN" ? "中文" : "English"}
              </button>
            ))}
          </div>
        </Row>
      </Section>

      <Section title="关于" desc="本作 v1.0.0 外部可分享版。">
        <p className="t-narration text-paper-200/70 text-sm leading-relaxed">
          《革命街没有尽头》AI 原生重构版。基于 v6 设计资产 + 8 个 JSON Schema 协议。
          <br />
          客户端不持有模型密钥，不保存权威状态。所有 AI 输出走叙事合同 + 提案制。
        </p>
      </Section>
    </div>
  );
}

function Section({
  title,
  desc,
  children,
}: {
  title: string;
  desc?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="archive-section">
      <h2 className="t-overline text-amber-glow mb-1">{title}</h2>
      {desc && <p className="t-meta text-paper-100/50 mb-4">{desc}</p>}
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function Row({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <div className="t-narration text-paper-100 text-sm">{label}</div>
        {help && <div className="t-meta text-paper-100/50 text-xs mt-0.5">{help}</div>}
      </div>
      <div>{children}</div>
    </div>
  );
}

function Toggle({ on, onChange }: { on: boolean; onChange: (b: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className={`w-12 h-7 rounded-full transition-colors relative ${
        on ? "bg-amber-glow" : "bg-ink-500"
      }`}
    >
      <span
        className={`absolute top-1 left-1 w-5 h-5 bg-paper-100 rounded-full transition-transform ${
          on ? "translate-x-5" : "translate-x-0"
        }`}
      />
    </button>
  );
}
