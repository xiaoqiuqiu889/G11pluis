// =============================================================================
// 革命街没有尽头 · 卷宗档案馆
// -----------------------------------------------------------------------------
// 七个 tab：时间线 / 证据 / 物件 / 记忆 / 因果种子 / 重演
// 决策红线：不显示精确数值（爱情值等）；只显示描述性内容
// ============================================================================

import { useParams, Link } from "react-router-dom";
import { Timeline } from "./Timeline";
import { Evidence } from "./Evidence";
import { Artifacts } from "./Artifacts";
import { Memories } from "./Memories";
import { CausalSeeds } from "./CausalSeeds";
import { Replay } from "./Replay";
import { useStore } from "@/lib/store";

const TABS = [
  { id: "timeline", label: "时间线" },
  { id: "evidence", label: "证据" },
  { id: "artifacts", label: "物件" },
  { id: "memories", label: "记忆" },
  { id: "causal", label: "因果种子" },
  { id: "replay", label: "重演" },
] as const;

export default function ArchivePage() {
  const { tab } = useParams<{ tab?: string }>();
  const active = (tab && TABS.find((t) => t.id === tab)?.id) ?? "timeline";

  return (
    <div className="min-h-screen pt-14 pb-12 px-4 md:px-8 max-w-6xl mx-auto">
      <header className="mb-6">
        <p className="t-overline text-amber-glow mb-2">记忆档案馆</p>
        <h1 className="t-display text-3xl md:text-4xl mb-2">本局卷宗</h1>
        <p className="t-narration text-paper-200/80 text-sm max-w-2xl">
          （你看到的这一份，是从已经发生的事里留下来的——不是剧透，是证据。每一个选择都连着一个还没关上的门。）
        </p>
      </header>

      <nav
        className="flex gap-2 overflow-x-auto pb-2 mb-6 -mx-1 px-1"
        role="tablist"
        aria-label="卷宗分类"
      >
        {TABS.map((t) => (
          <Link
            key={t.id}
            to={`/archive/${t.id}`}
            role="tab"
            aria-current={active === t.id ? "page" : undefined}
            className={`tab-pill ${active === t.id ? "aria-[current=page]:bg-amber-glow aria-[current=page]:text-ink-900" : ""}`}
          >
            {t.label}
          </Link>
        ))}
      </nav>

      <main role="tabpanel" aria-label={TABS.find((t) => t.id === active)?.label}>
        {active === "timeline" && <Timeline />}
        {active === "evidence" && <Evidence />}
        {active === "artifacts" && <Artifacts />}
        {active === "memories" && <Memories />}
        {active === "causal" && <CausalSeeds />}
        {active === "replay" && <Replay />}
      </main>
    </div>
  );
}

// 通用空态
export function ArchiveEmpty({ hint }: { hint: string }) {
  return (
    <div className="archive-section text-center py-12">
      <p className="t-italic text-paper-100/40">（这一栏还没有被填上——{hint}）</p>
    </div>
  );
}

// 取当前 store 的辅助
export function useArchiveData() {
  return {
    sceneMeta: useStore((s) => s.sceneMeta),
    progress: useStore((s) => s.sceneProgress),
    outcomes: useStore((s) => s.recentOutcomes),
    seeds: useStore((s) => s.causalSeedsActive),
    replayTickets: useStore((s) => s.replayTickets),
  };
}
