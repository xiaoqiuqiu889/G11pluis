// =============================================================================
// 革命街没有尽头 · 付费墙主页
// -----------------------------------------------------------------------------
// 决策 4：所有付费点从已结束 / 已解锁状态触发。
// 7 个商品视图 + 私人纪念品导出。
// ============================================================================

import { useNavigate, useParams } from "react-router-dom";
import { useStore } from "@/lib/store";
import { PRODUCTS, getProduct } from "./paywallProducts";
import { PassportView } from "./PassportView";
import { CollectorsView } from "./CollectorsView";
import { ParallelOps } from "./ParallelOps";
import { Credits } from "./Credits";
import { POVUnlock } from "./POVUnlock";
import { Keepsake } from "./Keepsake";

export default function Paywall() {
  const { product } = useParams<{ product?: string }>();
  const currentState = useStore((s) => s.currentState);
  const ownedProducts = useStore((s) => s.ownedProducts);
  const closePaywall = useStore((s) => s.closePaywall);

  // 路由到具体商品视图
  if (product) {
    const p = getProduct(product as any);
    if (!p) return <NotFound onClose={() => closePaywall()} />;
    return (
      <div className="min-h-screen pt-14 pb-12 px-4 md:px-8 max-w-5xl mx-auto">
        <BackBar onBack={() => history.back()} />
        {p.id === "passport" && <PassportView />}
        {p.id === "collectors" && <CollectorsView />}
        {p.id === "parallel_ops" && <ParallelOps />}
        {p.id === "credits" && <Credits />}
        {p.id === "pov_unlock" && <POVUnlock />}
        {p.id === "keepsake" && <Keepsake />}
      </div>
    );
  }

  return (
    <div className="min-h-screen pt-14 pb-12 px-4 md:px-8 max-w-5xl mx-auto">
      <header className="mb-8">
        <p className="t-overline text-amber-glow mb-2">商店</p>
        <h1 className="t-display text-3xl md:text-4xl mb-2">付费档位</h1>
        <p className="t-narration text-paper-200/80 text-sm max-w-2xl">
          （付费入口只在"已结束 / 已解锁"状态出现——不在主线中段。当前状态：
          <span className="text-amber-glow"> {currentState}</span>。这是设计红线，不写进游戏里。）
        </p>
      </header>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" role="list">
        {PRODUCTS.map((p) => {
          const owned = ownedProducts.includes(p.id);
          const available = p.availableFromState.includes(currentState);
          return (
            <ProductCard key={p.id} product={p} owned={owned} available={available} />
          );
        })}
      </div>
    </div>
  );
}

function ProductCard({
  product,
  owned,
  available,
}: {
  product: typeof PRODUCTS[number];
  owned: boolean;
  available: boolean;
}) {
  const nav = useNavigate();
  const featured = product.id === "passport" || product.id === "collectors";
  return (
    <article
      className="product-card flex flex-col"
      data-featured={featured}
      role="listitem"
    >
      <div className="flex items-start justify-between mb-2">
        <h3 className="t-display text-xl">{product.name}</h3>
        <div className="price-tag">
          {(product.priceCents / 100).toFixed(0)}
        </div>
      </div>
      <p className="t-narration text-paper-200/80 text-sm mb-3">{product.description}</p>
      <ul className="text-xs text-paper-100/60 space-y-1 mb-4 flex-1">
        {product.includes.map((inc, i) => (
          <li key={i} className="flex items-start gap-1.5">
            <span className="text-amber-glow">·</span>
            <span>{inc}</span>
          </li>
        ))}
      </ul>
      <div className="mt-auto">
        {owned ? (
          <span className="t-meta text-paper-100/40">已拥有</span>
        ) : available ? (
          <button
            className="action-btn w-full border-amber-glow text-amber-glow hover:bg-amber-glow/10"
            onClick={() => nav(`/paywall/${product.id}`)}
          >
            {product.cta}
          </button>
        ) : (
          <p className="t-meta text-paper-100/40" title="设计红线：付费点不在主线中段触发">
            （主线完成后可解锁）
          </p>
        )}
      </div>
    </article>
  );
}

function BackBar({ onBack }: { onBack: () => void }) {
  return (
    <button onClick={onBack} className="t-meta text-paper-200/70 hover:text-amber-glow mb-6">
      ← 返回商店
    </button>
  );
}

function NotFound({ onClose }: { onClose: () => void }) {
  return (
    <div className="min-h-screen pt-14 px-6 text-center">
      <p className="t-overline text-amber-glow mb-2">没有这个商品</p>
      <h1 className="t-display text-3xl mb-4">（货架上没有这一格）</h1>
      <button className="action-btn mx-auto" onClick={onClose}>
        回到街上
      </button>
    </div>
  );
}
