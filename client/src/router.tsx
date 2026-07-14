// =============================================================================
// 革命街没有尽头 · 路由
// -----------------------------------------------------------------------------
// 五个顶层路由：启动 / 三场景 / 卷宗 / 付费墙 / 设置
// 场景间跳转走 push state，不刷新整页。
// =============================================================================

import { createBrowserRouter, Navigate } from "react-router-dom";
import AppShell from "./components/AppShell";
import StartPage from "./features/start/StartPage";
import PhotoLab2008 from "./features/scenes/PhotoLab2008";
import Farewell2011 from "./features/scenes/Farewell2011";
import Reunion2024 from "./features/scenes/Reunion2024";
import ArchivePage from "./features/archive/ArchivePage";
import Paywall from "./features/commerce/Paywall";
import SettingsPage from "./features/settings/SettingsPage";
import { ErrorBoundary } from "./components/ErrorBoundary";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    errorElement: <ErrorBoundary />,
    children: [
      { index: true, element: <StartPage /> },
      { path: "scene/photo_lab_2008", element: <PhotoLab2008 /> },
      { path: "scene/farewell_2011", element: <Farewell2011 /> },
      { path: "scene/reunion_2024", element: <Reunion2024 /> },
      { path: "archive", element: <ArchivePage /> },
      { path: "archive/:tab", element: <ArchivePage /> },
      { path: "paywall", element: <Paywall /> },
      { path: "paywall/:product", element: <Paywall /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
