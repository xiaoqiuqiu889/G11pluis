// =============================================================================
// 革命街没有尽头 · 启动页
// -----------------------------------------------------------------------------
// 进入点：展示"旁观者"承诺 + 三场景入口 + 商品导览
// 决策 2：默认 = 旁观者（不允许在这里切到其他视角）
// 决策 4：免费样章入口
// ============================================================================

import { Link } from "react-router-dom";
import { useStore } from "@/lib/store";
import { audioEngine } from "@/audio/AudioEngine";

export default function StartPage() {
  const credits = useStore((s) => s.credits);
  const replayTickets = useStore((s) => s.replayTickets);
  const audioEnabled = useStore((s) => s.audioEnabled);
  const setAudio = useStore((s) => s.setAudio);

  const onEnableAudio = async () => {
    const ok = await audioEngine.start("prologue");
    if (ok) setAudio(true);
  };

  return (
    <div className="cinematic-frame" data-testid="start-page">
      <div className="grain-overlay" />
      <div className="vignette" />
      <div
        className="absolute inset-0 bg-cover bg-center"
        style={{ backgroundImage: "url(/assets/images/artifacts/01-graduation-photo-leila-worn.png)" }}
        aria-hidden
      />
      <div className="absolute inset-0 bg-gradient-to-b from-ink-900/70 via-ink-900/40 to-ink-900/95" />

      <div className="cinematic-aspect">
        <div className="relative z-10 w-full max-w-5xl px-6 py-16 text-center">
          <p className="t-overline text-amber-glow mb-4">AI 原生重构版 · 外部可分享</p>
          <h1 className="t-display text-5xl md:text-7xl tracking-cinematic mb-4">
            革命街没有尽头
          </h1>
          <p className="t-italic text-paper-200 text-lg md:text-xl mb-12">
            <em>Rev. Street · No End</em>
          </p>

          <div className="grid md:grid-cols-3 gap-3 mb-12 text-left">
            <PillarCard
              no="01"
              title="旁观者"
              desc="默认第三人称视角，用「你看到了 X」保持距离感。视角切换是付费解锁——免费样章里只暗示存在。"
            />
            <PillarCard
              no="02"
              title="三场景"
              desc="2008 地下放映室 → 2011 机场 → 2024 伊斯坦布尔。13 年因果，靠你早年的行为触发远期回响。"
            />
            <PillarCard
              no="03"
              title="付费门"
              desc="所有付费点从「已结束 / 已解锁」状态触发，不在主线中段。¥25 案件通行证 / ¥48 收藏版。"
            />
          </div>

          {/* 免费样章入口 */}
          <div className="glass-strong rounded-lg p-6 mb-6 max-w-2xl mx-auto">
            <p className="t-overline text-amber-glow mb-2">免费样章</p>
            <p className="t-narration text-paper-200 text-base mb-4">
              序章 + 三场景缩略（每场 5 分钟）+ 1 次 mandatory echo。
              <br />
              <span className="t-meta text-paper-100/50">
                已给你 {credits} 积分 / {replayTickets} 次重演 / 30 主调用
              </span>
            </p>
            <div className="flex flex-col sm:flex-row gap-2 justify-center">
              <Link to="/scene/photo_lab_2008" className="action-btn border-amber-glow text-amber-glow text-center">
                开始第一场 · 2008 夏
              </Link>
              <Link to="/cases" className="action-btn text-center" data-testid="open-case-selector">
                案件选择器（两案）
              </Link>
              <Link to="/paywall" className="action-btn text-center">
                案件通行证 ¥25
              </Link>
            </div>
          </div>

          {/* 声音启动提示 */}
          {!audioEnabled && (
            <button
              onClick={onEnableAudio}
              className="action-btn mx-auto"
              aria-label="点击启动声音（用户手势）"
            >
              ✶ 启动声音（用户手势）
            </button>
          )}

          <p className="t-meta text-paper-100/30 mt-8">
            旁观者 UX · 电影感 UI · 付费点 UX · v1.0
          </p>
        </div>
      </div>
    </div>
  );
}

function PillarCard({ no, title, desc }: { no: string; title: string; desc: string }) {
  return (
    <div className="glass rounded-md p-5 hover:border-amber-glow/40 transition-colors">
      <p className="t-num text-amber-glow/80 text-sm mb-2">{no}</p>
      <h3 className="t-display text-xl mb-2">{title}</h3>
      <p className="t-narration text-paper-200/80 text-sm leading-relaxed">{desc}</p>
    </div>
  );
}
