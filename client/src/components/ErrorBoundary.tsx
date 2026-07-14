// =============================================================================
// 革命街没有尽头 · 路由错误边界
// -----------------------------------------------------------------------------
// 兜底：UI 崩溃时给个不刺眼的黑色提示屏，提供回到启动页
// ============================================================================

import { Link, useRouteError } from "react-router-dom";

export function ErrorBoundary() {
  const error = useRouteError() as { message?: string; statusText?: string };
  return (
    <div className="cinematic-frame grain-overlay">
      <div className="vignette" />
      <div className="cinematic-aspect">
        <div className="text-center max-w-md px-6">
          <p className="t-overline text-amber-glow mb-4">信号中断</p>
          <h1 className="t-display text-3xl mb-4">这一段没有留住</h1>
          <p className="t-narration mb-8 text-paper-200">
            （画面停了一下。灯泡闪了一闪。银幕上什么都没有——只有几粒灰尘在光柱里慢慢落下来。）
          </p>
          {error?.message && (
            <p className="t-meta mb-6 text-paper-100/40">err: {error.message}</p>
          )}
          <Link
            to="/"
            className="action-btn inline-block border-amber-glow text-amber-glow hover:bg-amber-glow/10"
          >
            回到街上
          </Link>
        </div>
      </div>
    </div>
  );
}
