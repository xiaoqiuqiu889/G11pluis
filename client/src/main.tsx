// =============================================================================
// 革命街没有尽头 · React 渲染入口
// -----------------------------------------------------------------------------
// 1. 加载全局样式（cinematic + typography + animations）
// 2. 注册 prefers-reduced-motion 检测
// 3. 注入 Electron IPC 桥接 polyfill（浏览器降级）
// 4. 挂载 App
// =============================================================================

import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/tailwind.css";
import "./styles/cinematic.css";
import "./styles/typography.css";
import "./styles/animations.css";

// 减动态模式检测
const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
document.documentElement.dataset.reducedMotion = mq.matches ? "true" : "false";
mq.addEventListener("change", (e) => {
  document.documentElement.dataset.reducedMotion = e.matches ? "true" : "false";
});

// 浏览器环境 polyfill：没有 electronAPI 时给一个空实现（mock）
if (typeof window !== "undefined" && !window.electronAPI) {
  (window as unknown as { electronAPI: unknown }).electronAPI = {
    appInfo: async () => ({
      version: "1.0.0-browser",
      platform: "web",
      isDev: true,
      userDataPath: "/",
    }),
    window: { setFullscreen: async () => true },
    save: { export: async () => ({ ok: false, reason: "browser" }) },
    audio: { setChapter: async () => true },
    commerce: { openPaywall: async () => true },
    on: () => () => undefined,
  };
}

const container = document.getElementById("root");
if (!container) throw new Error("#root not found");

createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
