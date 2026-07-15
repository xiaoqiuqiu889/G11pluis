// =============================================================================
// 革命街没有尽头 · 路由
// -----------------------------------------------------------------------------
// W12: case selector + 6 个场景路由（3 case_01 + 3 case_02）
// 五个顶层路由：启动 / case 选择 / 三场景 / 卷宗 / 付费墙 / 设置
// 场景间跳转走 push state，不刷新整页。
// =============================================================================

import { createBrowserRouter, Navigate } from "react-router-dom";
import AppShell from "./components/AppShell";
import StartPage from "./features/start/StartPage";
import CaseSelector from "./features/start/CaseSelector";
import PhotoLab2008 from "./features/scenes/PhotoLab2008";
import Farewell2011 from "./features/scenes/Farewell2011";
import Reunion2024 from "./features/scenes/Reunion2024";
import Meeting1985 from "./features/scenes/Meeting1985";
import Farewell1989 from "./features/scenes/Farewell1989";
import Reunion2008 from "./features/scenes/Reunion2008";
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
      // W12: case selector
      { path: "cases", element: <CaseSelector /> },
      // case_01 三个场景
      { path: "scene/photo_lab_2008", element: <PhotoLab2008 /> },
      { path: "scene/farewell_2011", element: <Farewell2011 /> },
      { path: "scene/reunion_2024", element: <Reunion2024 /> },
      // case_02 三个场景
      { path: "scene/1985_meeting", element: <Meeting1985 /> },
      { path: "scene/1989_farewell", element: <Farewell1989 /> },
      { path: "scene/2008_reunion", element: <Reunion2008 /> },
      { path: "archive", element: <ArchivePage /> },
      { path: "archive/:tab", element: <ArchivePage /> },
      { path: "paywall", element: <Paywall /> },
      { path: "paywall/:product", element: <Paywall /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
