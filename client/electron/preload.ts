// =============================================================================
// 革命街没有尽头 · Electron 预加载脚本
// -----------------------------------------------------------------------------
// 暴露最小 API 给 React 渲染进程，保持上下文隔离。
// 所有 IPC 都用 handle/invoke 或 send/on 双工模式。
// =============================================================================

import { contextBridge, ipcRenderer } from "electron";

export interface AppInfo {
  version: string;
  platform: NodeJS.Platform;
  isDev: boolean;
  userDataPath: string;
}

export interface ExportResult {
  ok: boolean;
  reason?: string;
  path?: string;
}

const api = {
  appInfo: (): Promise<AppInfo> => ipcRenderer.invoke("app:info"),

  window: {
    setFullscreen: (full: boolean): Promise<boolean> =>
      ipcRenderer.invoke("window:set-fullscreen", full),
  },

  save: {
    export: (name: string, data: unknown): Promise<ExportResult> =>
      ipcRenderer.invoke("save:export", { name, data }),
  },

  audio: {
    setChapter: (chapter: string): Promise<boolean> =>
      ipcRenderer.invoke("audio:play-chapter", chapter),
  },

  commerce: {
    openPaywall: (): Promise<boolean> => ipcRenderer.invoke("commerce:open-paywall"),
  },

  // 事件订阅：渲染进程侧订阅主进程推过来的事件
  on: (channel: string, listener: (payload: unknown) => void) => {
    const allowed = new Set([
      "nav:home",
      "nav:archive",
      "run:save",
      "run:replay",
      "observer:toggle",
      "audio:chapter",
      "commerce:open",
    ]);
    if (!allowed.has(channel)) return () => undefined;
    const wrapped = (_e: Electron.IpcRendererEvent, payload: unknown) => listener(payload);
    ipcRenderer.on(channel, wrapped);
    return () => ipcRenderer.removeListener(channel, wrapped);
  },
};

export type ElectronAPI = typeof api;

try {
  contextBridge.exposeInMainWorld("electronAPI", api);
} catch (e) {
  // 上下文桥失败时直接挂到 window（仅 dev 模式兜底）
  (window as unknown as { electronAPI: ElectronAPI }).electronAPI = api;
}
