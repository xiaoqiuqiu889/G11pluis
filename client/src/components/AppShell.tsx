// =============================================================================
// 革命街没有尽头 · 顶层布局壳
// -----------------------------------------------------------------------------
// 包含：标题栏 / 路由出口 / 全局浮动元素（降级徽章、付费墙）
// =============================================================================

import { Outlet, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { useStore } from "@/lib/store";
import { DegradationBadge } from "./DegradationBadge";
import { PaywallOverlay } from "@/features/commerce/PaywallOverlay";
import { TitleBar } from "./TitleBar";

export default function AppShell() {
  const { pathname } = useLocation();
  const networkState = useStore((s) => s.networkState);

  // 路由变化时滚动到顶
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [pathname]);

  return (
    <div className="relative min-h-screen bg-ink-900 text-paper-100">
      <TitleBar />
      <DegradationBadge />

      <main
        className="relative"
        aria-busy={networkState === "connecting" || networkState === "streaming"}
        aria-live="polite"
      >
        <Outlet />
      </main>

      <PaywallOverlay />
    </div>
  );
}
