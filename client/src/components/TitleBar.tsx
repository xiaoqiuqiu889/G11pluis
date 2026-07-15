// =============================================================================
// 革命街没有尽头 · 自定义标题栏
// -----------------------------------------------------------------------------
// 标题栏上方留 36px 给 Electron 拖拽 + 关闭窗口
// ============================================================================

import { Link, useLocation } from "react-router-dom";
import { useStore } from "@/lib/store";

export function TitleBar() {
  const { pathname } = useLocation();
  const povMode = useStore((s) => s.povMode);
  const isInScene = pathname.startsWith("/scene/");

  return (
    <header
      className="g1n-titlebar fixed inset-x-0 top-0 z-50 h-9 flex items-center justify-between gap-2 px-2 sm:px-4 glass-strong"
      style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
    >
      <div className="g1n-titlebar-brand flex min-w-0 items-center gap-2 sm:gap-3 whitespace-nowrap text-xs t-meta" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
        <Link to="/" className="hover:text-amber-glow transition-colors" aria-label="返回启动页">
          革命街
        </Link>
        <span className="text-paper-100/30">·</span>
        <span className="t-overline">Rev. Street · No End</span>
        {isInScene && (
          <>
            <span className="text-paper-100/30">·</span>
            <span className="t-overline text-amber-glow">
              旁观者视角
            </span>
          </>
        )}
      </div>

      <nav
        className="g1n-titlebar-nav flex shrink-0 items-center gap-0 sm:gap-1 text-xs whitespace-nowrap"
        style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
        aria-label="主导航"
      >
        <NavLink to="/" current={pathname}>
          启动
        </NavLink>
        <NavLink to="/archive" current={pathname}>
          卷宗
        </NavLink>
        <NavLink to="/paywall" current={pathname}>
          商店
        </NavLink>
        <NavLink to="/settings" current={pathname}>
          设置
        </NavLink>
      </nav>
    </header>
  );
}

function NavLink({
  to,
  current,
  children,
}: {
  to: string;
  current: string;
  children: React.ReactNode;
}) {
  const active = to === "/" ? current === "/" : current.startsWith(to);
  return (
    <Link
      to={to}
      className={`px-3 py-1.5 rounded transition-colors ${
        active ? "text-amber-glow" : "text-paper-200/70 hover:text-paper-100"
      }`}
      aria-current={active ? "page" : undefined}
    >
      {children}
    </Link>
  );
}
