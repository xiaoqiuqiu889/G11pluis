// =============================================================================
// 革命街没有尽头 · 案件选择器 (W12)
// -----------------------------------------------------------------------------
// V5 命题"内容可规模化"的客户端落地：列出所有注册案件，玩家可任选进入
// 每个案件 3 个场景 + 跨案母题对应表（一句文案）
// 决策 2 补充条款：每个案件的第一句台词必须引用玩家早期行为
// 决策 5：第二案与第一案共享积分 / 票 / 主调用配额
// ============================================================================

import { Link } from "react-router-dom";
import { CASE_LIST } from "@/mocks/scenes";
import { setCase } from "@/audio/AudioEngine";

export default function CaseSelector() {
  return (
    <div className="cinematic-frame" data-testid="case-selector-page">
      <div className="grain-overlay" />
      <div className="vignette" />
      <div className="absolute inset-0 bg-gradient-to-b from-ink-900/85 via-ink-900/65 to-ink-900/95" />

      <div className="cinematic-aspect">
        <div className="relative z-10 w-full max-w-6xl px-6 py-16">
          <p className="t-overline text-amber-glow mb-3 text-center">AI 原生 · 多案件</p>
          <h1 className="t-display text-4xl md:text-5xl tracking-cinematic mb-3 text-center">
            选一个案件进入
          </h1>
          <p className="t-italic text-paper-200 text-center text-lg mb-10">
            每个案件 3 个场景 / 跨年代回响 / 12 行为词汇表
          </p>

          <div className="grid md:grid-cols-2 gap-6">
            {CASE_LIST.map((c) => (
              <div
                key={c.caseSlug}
                className="glass-strong rounded-lg p-6 flex flex-col"
                data-testid={`case-card-${c.caseSlug}`}
              >
                <div className="flex items-center justify-between mb-2">
                  <p className="t-overline text-amber-glow">
                    {c.caseSlug === "case_01_revolution_street" ? "案 01" : "案 02"}
                  </p>
                  <span className="t-meta text-paper-100/50">{c.sceneIds.length} 场景</span>
                </div>
                <h2 className="t-display text-2xl md:text-3xl tracking-cinematic mb-1">
                  {c.displayName}
                </h2>
                <p className="t-italic text-paper-200 text-base mb-4">
                  <em>{c.subtitle}</em>
                </p>

                <div className="space-y-1 mb-5 text-paper-100/80 text-sm">
                  {c.sceneIds.map((sid) => (
                    <SceneLink key={sid} sceneId={sid} caseSlug={c.caseSlug} />
                  ))}
                </div>

                <div className="mt-auto flex items-center gap-3">
                  <Link
                    to="/"
                    className="action-btn"
                    data-testid={`back-from-${c.caseSlug}`}
                  >
                    ← 返回
                  </Link>
                  <span className="t-meta text-paper-100/40">
                    决策 2 补充条款：进入第一场前玩家早期行为必须被引用
                  </span>
                </div>
              </div>
            ))}
          </div>

          <p className="t-meta text-paper-100/30 mt-10 text-center">
            W12 · V5 命题"内容可规模化"工程层实证 · 100% 复用 schema / 12 行为词汇表 / mandatory echo
          </p>
        </div>
      </div>
    </div>
  );
}

function SceneLink({ sceneId, caseSlug }: { sceneId: string; caseSlug: string }) {
  // 提前切 AudioEngine 路径表，确保 player 进入前 audio 资源已就位
  if (typeof window !== "undefined") {
    setCase(caseSlug);
  }
  return (
    <Link
      to={`/scene/${sceneId}`}
      className="block hover:text-amber-glow transition-colors"
      data-testid={`scene-link-${sceneId}`}
    >
      · {sceneId}
    </Link>
  );
}
