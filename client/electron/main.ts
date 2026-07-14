// =============================================================================
// 革命街没有尽头 · Electron 主进程
// -----------------------------------------------------------------------------
// 职责：窗口创建、菜单、原生 IPC、操作系统桥接。
// 不持有任何业务逻辑，所有状态由前端 React + Zustand 维护。
// =============================================================================

import {
  app,
  BrowserWindow,
  Menu,
  ipcMain,
  shell,
  dialog,
  nativeTheme,
} from "electron";
import * as path from "path";
import * as fs from "fs";

const isDev = process.env.NODE_ENV === "development" || !app.isPackaged;
const VITE_DEV_URL = process.env.VITE_DEV_URL || "http://localhost:5173";

// 防止多开
const gotSingleLock = app.requestSingleInstanceLock();
if (!gotSingleLock) {
  app.quit();
}

let mainWindow: BrowserWindow | null = null;

function resolveEntryPath(): { url?: string; file?: string } {
  if (isDev) return { url: VITE_DEV_URL };
  return { file: path.join(__dirname, "..", "dist", "index.html") };
}

function createMainWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 390,
    minHeight: 600,
    show: false,
    backgroundColor: "#08080a",
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#0d0d10",
      symbolColor: "#f1ecdf",
      height: 36,
    },
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  // 暗色主题锁定
  nativeTheme.themeSource = "dark";

  // 内容安全策略：仅在生产模式设置
  if (!isDev) {
    win.webContents.session.webRequest.onHeadersReceived((details, callback) => {
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          "Content-Security-Policy": [
            "default-src 'self'; img-src 'self' data: file:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self' http://localhost:* ws:;",
          ],
        },
      });
    });
  }

  // 优雅打开：先隐藏再 ready-to-show，避免白屏闪烁
  win.once("ready-to-show", () => {
    win.show();
  });

  // 外部链接用系统浏览器
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  // 阻止应用内导航（除了 _blank）
  win.webContents.on("will-navigate", (e, url) => {
    if (!url.startsWith(VITE_DEV_URL) && !url.startsWith("file://")) {
      e.preventDefault();
      shell.openExternal(url);
    }
  });

  const entry = resolveEntryPath();
  if (entry.url) {
    void win.loadURL(entry.url);
    if (isDev) win.webContents.openDevTools({ mode: "detach" });
  } else if (entry.file) {
    void win.loadFile(entry.file);
  }

  win.on("closed", () => {
    if (mainWindow === win) mainWindow = null;
  });

  return win;
}

function buildMenu(): void {
  const isMac = process.platform === "darwin";
  const template: Electron.MenuItemConstructorOptions[] = [
    ...(isMac
      ? [
          {
            label: app.name,
            submenu: [
              { role: "about" as const, label: "关于" },
              { type: "separator" as const },
              { role: "services" as const },
              { type: "separator" as const },
              { role: "hide" as const, label: "隐藏" },
              { role: "hideOthers" as const, label: "隐藏其它" },
              { role: "unhide" as const, label: "显示全部" },
              { type: "separator" as const },
              { role: "quit" as const, label: "退出" },
            ],
          },
        ]
      : []),
    {
      label: "档案",
      submenu: [
        {
          label: "返回启动页",
          accelerator: "CmdOrCtrl+Shift+H",
          click: () => mainWindow?.webContents.send("nav:home"),
        },
        {
          label: "打开卷宗",
          accelerator: "CmdOrCtrl+A",
          click: () => mainWindow?.webContents.send("nav:archive"),
        },
        { type: "separator" },
        {
          label: "保存本局",
          accelerator: "CmdOrCtrl+S",
          click: () => mainWindow?.webContents.send("run:save"),
        },
      ],
    },
    {
      label: "观察",
      submenu: [
        {
          label: "切换旁观者 / 演员",
          accelerator: "CmdOrCtrl+O",
          click: () => mainWindow?.webContents.send("observer:toggle"),
        },
        {
          label: "重演本节点",
          accelerator: "CmdOrCtrl+R",
          click: () => mainWindow?.webContents.send("run:replay"),
        },
      ],
    },
    {
      label: "显示",
      submenu: [
        { role: "reload", label: "重新载入" },
        { role: "forceReload", label: "强制重载" },
        { role: "toggleDevTools", label: "开发者工具" },
        { type: "separator" },
        { role: "resetZoom", label: "实际大小" },
        { role: "zoomIn", label: "放大" },
        { role: "zoomOut", label: "缩小" },
        { type: "separator" },
        { role: "togglefullscreen", label: "全屏" },
      ],
    },
    {
      label: "帮助",
      submenu: [
        {
          label: "关于本作",
          click: () => {
            void dialog.showMessageBox(mainWindow!, {
              type: "info",
              title: "革命街没有尽头",
              message: "革命街没有尽头 · AI 原生重构版",
              detail:
                "外部可分享版 · v1.0.0\n\n旁观者 UX · 电影感 UI · 付费点 UX\n\n© 2026 G1 AI Native",
              buttons: ["好的"],
            });
          },
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// =============================================================================
// IPC 处理器
// =============================================================================

ipcMain.handle("app:info", () => ({
  version: app.getVersion(),
  platform: process.platform,
  isDev,
  userDataPath: app.getPath("userData"),
}));

ipcMain.handle("window:set-fullscreen", (_e, fullscreen: boolean) => {
  if (mainWindow) mainWindow.setFullScreen(fullscreen);
  return true;
});

ipcMain.handle("save:export", async (_e, payload: { name: string; data: unknown }) => {
  if (!mainWindow) return { ok: false, reason: "no_window" };
  const result = await dialog.showSaveDialog(mainWindow, {
    title: "导出私人纪念品",
    defaultPath: `${payload.name}.json`,
    filters: [{ name: "JSON", extensions: ["json"] }],
  });
  if (result.canceled || !result.filePath) return { ok: false, reason: "canceled" };
  await fs.promises.writeFile(
    result.filePath,
    JSON.stringify(payload.data, null, 2),
    "utf-8",
  );
  return { ok: true, path: result.filePath };
});

ipcMain.handle("audio:play-chapter", (_e, chapter: string) => {
  // 由前端 AudioEngine 处理，主进程只做桥接
  mainWindow?.webContents.send("audio:chapter", chapter);
  return true;
});

ipcMain.handle("commerce:open-paywall", () => {
  mainWindow?.webContents.send("commerce:open");
  return true;
});

// =============================================================================
// 生命周期
// =============================================================================

app.on("second-instance", () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

app.whenReady().then(() => {
  buildMenu();
  mainWindow = createMainWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      mainWindow = createMainWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
