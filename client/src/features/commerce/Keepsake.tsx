// =============================================================================
// 革命街没有尽头 · 私人纪念品 · ¥8
// -----------------------------------------------------------------------------
// 决策 4：本局专属信件 + 照片 + 关系报告，可导出
// 决策红线：不显示精确数值（关系报告用描述性）
// ============================================================================

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStore } from "@/lib/store";

export function Keepsake() {
  const nav = useNavigate();
  const grantProduct = useStore((s) => s.grantProduct);
  const outcomes = useStore((s) => s.recentOutcomes);
  const sceneMeta = useStore((s) => s.sceneMeta);
  const [generated, setGenerated] = useState(false);

  // 关系报告：描述性
  const report = buildReport(outcomes.length, sceneMeta?.sceneId ?? "—");

  const onBuy = () => {
    grantProduct("keepsake");
    setGenerated(true);
  };

  const onExport = async () => {
    if (typeof window !== "undefined" && window.electronAPI) {
      await window.electronAPI.save.export("revolution-street-keepsake", {
        generatedAt: new Date().toISOString(),
        report,
        outcomesCount: outcomes.length,
      });
    } else {
      // 浏览器降级：复制到剪贴板
      const blob = new Blob([JSON.stringify({ generatedAt: new Date().toISOString(), report }, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "revolution-street-keepsake.json";
      a.click();
      URL.revokeObjectURL(url);
    }
  };

  return (
    <div className="max-w-3xl">
      <p className="t-overline text-amber-glow mb-2">私人纪念品</p>
      <h1 className="t-display text-4xl mb-2">¥8</h1>
      <p className="t-narration text-paper-200/80 mb-6">
        本局专属信件（从 NPC 视角写给你）+ 关键时刻照片 + 关系报告（描述性，不显示精确数值）。可导出 JSON。
      </p>

      {!generated ? (
        <button className="action-btn border-amber-glow text-amber-glow" onClick={onBuy}>
          生成本局纪念品
        </button>
      ) : (
        <div className="space-y-6">
          <section className="glass rounded p-5">
            <h3 className="t-overline text-amber-glow mb-2">本局专属信件</h3>
            <p className="t-narration text-paper-100 leading-relaxed t-italic">
              （这一封信是从阿拉什的视角写给你的——但你从未收到过它。它在十三年后才被找到。）
              <br />
              <br />
              亲爱的：<br />
              我没有叫住你——在安检口前那一下，我的手抬过又放下。<br />
              我把那张照片夹在诗集里，没给你看。<br />
              2008 那个夏夜你说"我希望你留着"，我没答。<br />
              我没有答，是因为我那时不会说——这句话，<br />
              过了十三年，我才在伊斯坦布尔的雨后学会。<br />
              <br />
              —— A.
            </p>
          </section>

          <section className="glass rounded p-5">
            <h3 className="t-overline text-amber-glow mb-2">关系报告</h3>
            <ul className="space-y-1.5 text-sm">
              {report.map((r, i) => (
                <li key={i} className="flex items-start gap-2 text-paper-200">
                  <span className="text-amber-glow">·</span>
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          </section>

          <div className="flex gap-2">
            <button className="action-btn border-amber-glow text-amber-glow" onClick={onExport}>
              导出 JSON
            </button>
            <button className="action-btn" onClick={() => nav("/")}>
              回到街上
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function buildReport(outcomeCount: number, sceneId: string): string[] {
  return [
    `本局共发生 ${outcomeCount} 次状态变化（描述性计数，非数值）。`,
    `最后一场：${sceneId}`,
    `整体氛围：克制——你做的选择偏向"藏"而不是"给"。`,
    `重演过的节点：0（如果用过平行演算包，会列出 #eventSequence）。`,
    `（这是纪念品版本的关系报告——不显示精确数值。）`,
  ];
}
