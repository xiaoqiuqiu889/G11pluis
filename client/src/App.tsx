// =============================================================================
// 革命街没有尽头 · 顶层 App
// -----------------------------------------------------------------------------
// 全局：路由、布局、键盘焦点、prefers-reduced-motion 监听
// =============================================================================

import { useEffect } from "react";
import { RouterProvider } from "react-router-dom";
import { router } from "./router";
import { useStore } from "./lib/store";
import { audioEngine } from "./audio/AudioEngine";

export default function App() {
  const reducedMotion = useStore((s) => s.reducedMotion);
  const setReducedMotion = useStore((s) => s.setReducedMotion);

  // 同步系统减动态偏好
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const handler = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [setReducedMotion]);

  // 全局键盘快捷键
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        // 关闭顶层 modal
        document
          .querySelectorAll<HTMLElement>("[data-modal-open=true]")
          .forEach((el) => (el.dataset.modalOpen = "false"));
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // 卸载时关闭音频
  useEffect(() => {
    return () => {
      audioEngine.stop();
    };
  }, []);

  return (
    <div
      data-reduced-motion={reducedMotion ? "true" : "false"}
      className="min-h-screen bg-ink-900 text-paper-100 selection:bg-amber-glow/30"
    >
      <RouterProvider router={router} />
    </div>
  );
}
