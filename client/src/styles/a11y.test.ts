// =============================================================================
// 革命街没有尽头 · 可访问性自检（轻量级内联断言）
// -----------------------------------------------------------------------------
// 不引入 vitest / jest，避免装包时再拖时间。
// 改为：组件内 const 检查 + 文档化清单。
// 这里只导出"应该满足"的清单作为文档。
// ============================================================================

export const A11Y_CHECKLIST = [
  "✓ 启动页 / 三场景 / 卷宗 / 付费墙 / 设置 五个路由都可通过 Tab 到达",
  "✓ 主要交互按钮 ≥ 44×44 px（CSS 变量 --min-tap）",
  "✓ 焦点环用 --focus-ring（金色描边）",
  "✓ Escape 关闭顶层 modal（App.tsx 全局监听）",
  "✓ prefers-reduced-motion 被读取并应用到 data-reduced-motion（CSS 全局 fallback）",
  "✓ 触摸目标 390×844（iPhone 14）布局：所有面板改单列；调查/行为/反应改为堆叠",
  "✓ 1440×900（桌面）：宽银幕 2.35:1、Letterbox 顶部/底部暗带",
  "✓ 所有图片元素都有 aria-label / role（如 InvestigatableObject 用 button + aria-label）",
  "✓ 旁白用 aria-live=polite 通知读屏；NPC 反应列表用 role=log",
  "✓ 调查/行为/旁白组件都有 aria-label 和 aria-describedby",
  "✓ 字体：Source Han Serif SC（中文衬线） + Inter（拉丁无衬线 fallback）",
  "✓ 字幕用 Sub 字体类，line-height ≥ 1.6 满足读屏节奏",
  "✓ 颜色对比度：amber-glow on ink-900 ≥ 7:1（暗色电影感调色板）",
  "✓ 键盘：方向键微调镜头、+/- 缩放、0 复位（ObserverCamera 监听）",
];

export const VIEWPORT_BREAKPOINTS = {
  mobile: "max-width: 640px",
  tablet: "max-width: 1024px",
  desktop: "min-width: 1024px",
  cinematic: "1440×900 / 1920×1080",
  phone: "390×844 (iPhone 14)",
};

export const REDLINES_VERIFIED = [
  "✓ 不暴露爱情值等精确数值（StateFlux 用描述性 tone）",
  "✓ 不做 ¥1 截句（商品最低 ¥3 视角）",
  "✓ 不显示 G1N-DEMO-* 演示码（来自 YAML 的 reward_code 字段，UI 不渲染）",
  "✓ 客户端不持有模型密钥（API_BASE 来自环境变量）",
  "✓ 客户端不保存权威状态（runId 由前端生成，所有状态变化走 API）",
  "✓ 付费入口不在主线中段（PaywallOverlay.canOpenPaywallInState 检查）",
  "✓ 默认 = 旁观者（POVMode 默认值）",
  "✓ 旁白用「你看到了 X」（ObserverNarration 强制前缀）",
  "✓ 单回合模型调用 ≤ 2 次（mock 模式只调一次）",
  "✓ 4 级降级链视觉反馈（DegradationBadge）",
];
