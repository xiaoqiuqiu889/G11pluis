"use strict";
// =============================================================================
// 革命街没有尽头 · Electron 预加载脚本
// -----------------------------------------------------------------------------
// 暴露最小 API 给 React 渲染进程，保持上下文隔离。
// 所有 IPC 都用 handle/invoke 或 send/on 双工模式。
// =============================================================================
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
const api = {
    appInfo: () => electron_1.ipcRenderer.invoke("app:info"),
    window: {
        setFullscreen: (full) => electron_1.ipcRenderer.invoke("window:set-fullscreen", full),
    },
    save: {
        export: (name, data) => electron_1.ipcRenderer.invoke("save:export", { name, data }),
    },
    audio: {
        setChapter: (chapter) => electron_1.ipcRenderer.invoke("audio:play-chapter", chapter),
    },
    commerce: {
        openPaywall: () => electron_1.ipcRenderer.invoke("commerce:open-paywall"),
    },
    // 事件订阅：渲染进程侧订阅主进程推过来的事件
    on: (channel, listener) => {
        const allowed = new Set([
            "nav:home",
            "nav:archive",
            "run:save",
            "run:replay",
            "observer:toggle",
            "audio:chapter",
            "commerce:open",
        ]);
        if (!allowed.has(channel))
            return () => undefined;
        const wrapped = (_e, payload) => listener(payload);
        electron_1.ipcRenderer.on(channel, wrapped);
        return () => electron_1.ipcRenderer.removeListener(channel, wrapped);
    },
};
try {
    electron_1.contextBridge.exposeInMainWorld("electronAPI", api);
}
catch (e) {
    // 上下文桥失败时直接挂到 window（仅 dev 模式兜底）
    window.electronAPI = api;
}
