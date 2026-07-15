// =============================================================================
// 革命街 AI 原生重构版 · 端到端测试工程
// -----------------------------------------------------------------------------
// 系统化跑所有路由 → 截图 → 抓 console / network 错误 → 输出 bug 报告
// W12-E2E 启动器：所有 UI 修复前先用这个扫描全量 bug
// =============================================================================

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const SCREENSHOT_DIR = 'D:/G1-ai-native/e2e-screenshots';
const REPORT_PATH = 'D:/G1-ai-native/e2e-screenshots/e2e-report.json';

const ROUTES = [
  // case_01
  { name: 'start-page',                    url: 'http://localhost:5173/',                           case: 'case_01' },
  { name: 'case-selector',                 url: 'http://localhost:5173/cases',                       case: 'both'   },
  { name: 'case_01-photo_lab_2008',        url: 'http://localhost:5173/scene/photo_lab_2008',       case: 'case_01' },
  { name: 'case_01-farewell_2011',         url: 'http://localhost:5173/scene/farewell_2011',        case: 'case_01' },
  { name: 'case_01-reunion_2024',          url: 'http://localhost:5173/scene/reunion_2024',         case: 'case_01' },
  // case_02
  { name: 'case_02-1985_meeting',          url: 'http://localhost:5173/scene/1985_meeting',         case: 'case_02' },
  { name: 'case_02-1989_farewell',         url: 'http://localhost:5173/scene/1989_farewell',        case: 'case_02' },
  { name: 'case_02-2008_reunion',          url: 'http://localhost:5173/scene/2008_reunion',         case: 'case_02' },
  // 辅助
  { name: 'archive',                       url: 'http://localhost:5173/archive',                    case: 'both'   },
  { name: 'settings',                      url: 'http://localhost:5173/settings',                   case: 'both'   },
];

const SCENES_WITH_AUDIO = ['photo_lab_2008', 'farewell_2011', 'reunion_2024', '1985_meeting', '1989_farewell', '2008_reunion'];

(async () => {
  if (!fs.existsSync(SCREENSHOT_DIR)) fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

  console.log('=== G1N E2E 端到端测试工程启动 ===');
  console.log(`截图目录: ${SCREENSHOT_DIR}`);
  console.log(`路由数: ${ROUTES.length}`);
  console.log('');

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: 'zh-CN',
  });

  const report = {
    startTime: new Date().toISOString(),
    endTime: null,
    summary: { total: ROUTES.length, ok: 0, bugs: 0, fatal: 0 },
    routes: [],
    globalBugs: [],
  };

  for (const route of ROUTES) {
    console.log(`\n--- 测试: ${route.name} (${route.url}) ---`);
    const page = await context.newPage();

    const consoleLogs = [];
    const pageErrors = [];
    const failedRequests = [];

    page.on('console', msg => consoleLogs.push({ type: msg.type(), text: msg.text() }));
    page.on('pageerror', err => pageErrors.push(err.message));
    page.on('requestfailed', req => failedRequests.push({
      url: req.url(),
      error: req.failure()?.errorText,
    }));

    let status = 'unknown';
    let httpStatus = null;
    let pageInfo = {};

    try {
      const response = await page.goto(route.url, { waitUntil: 'networkidle', timeout: 15000 });
      httpStatus = response ? response.status() : null;
      await page.waitForTimeout(1500);

      // 截图
      const screenshotPath = path.join(SCREENSHOT_DIR, `${route.name}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true });

      // 提取页面信息
      pageInfo = await page.evaluate((r) => {
        const root = document.getElementById('root');
        const cinematicFrame = document.querySelector('.cinematic-frame');
        const cinematicAspect = document.querySelector('.cinematic-aspect');
        const bgImageEl = document.querySelector('[style*="background-image"]');
        const grainOverlay = document.querySelector('.grain-overlay');
        const actionButtons = document.querySelectorAll('.action-btn');
        const investigationPanel = document.querySelector('[class*="investigation"], [class*="Investigation"]');
        const narration = document.querySelector('[class*="narration"], [class*="Narration"]');
        const observerHint = document.querySelector('[class*="hint"], [class*="Hint"]');
        const sceneStatusBar = document.querySelector('[class*="status"], [class*="Status"]');
        const caseCard = document.querySelector('[data-testid^="case-card"]');
        const h1Elements = document.querySelectorAll('h1');

        // 检查布局问题
        const issues = [];

        // 1. 根是否为空
        if (!root || root.innerText.trim().length === 0) {
          issues.push('ROOT_EMPTY');
        }

        // 2. 场景主图是否加载（接受 inline style 或 img 标签）
        let bgChecked = false;
        if (bgImageEl) {
          const bgImg = bgImageEl.style.backgroundImage;
          if (bgImg && bgImg.includes('url(')) {
            const url = bgImg.match(/url\(["']?([^"')]+)["']?\)/)?.[1];
            if (url) {
              const testImg = new Image();
              testImg.src = url;
              if (!testImg.complete || testImg.naturalWidth === 0) {
                issues.push('BG_IMAGE_BROKEN: ' + url);
              }
              bgChecked = true;
            }
          } else if (bgImg && bgImg.includes('gradient')) {
            bgChecked = true; // 渐变背景也算 OK
          } else {
            issues.push('BG_IMAGE_MISSING_INLINE_STYLE');
          }
        }
        if (!bgChecked) {
          // 也检查 <img> 标签 + 检查 gradient 背景 div
          const hasGradient = !!document.querySelector('.bg-gradient-to-b');
          if (!hasGradient && !document.querySelector('img')) {
            issues.push('BG_IMAGE_NOT_FOUND');
          }
        }

        // 3. cinematic-frame / aspect 是否全屏
        if (cinematicFrame) {
          const rect = cinematicFrame.getBoundingClientRect();
          if (rect.width < 1000 || rect.height < 600) {
            issues.push(`CINEMATIC_FRAME_TOO_SMALL: ${rect.width}x${rect.height}`);
          }
        } else {
          issues.push('CINEMATIC_FRAME_NOT_FOUND');
        }

        // 4. 动作按钮是否堆叠
        if (actionButtons.length > 0) {
          const positions = Array.from(actionButtons).map(btn => {
            const r = btn.getBoundingClientRect();
            return { x: r.x, y: r.y, w: r.width, h: r.height, text: btn.innerText.substring(0, 10) };
          });
          // 检查是否有重叠
          for (let i = 0; i < positions.length; i++) {
            for (let j = i + 1; j < positions.length; j++) {
              const a = positions[i], b = positions[j];
              if (Math.abs(a.x - b.x) < 5 && Math.abs(a.y - b.y) < 5) {
                issues.push(`ACTION_BTN_OVERLAP: ${a.text} & ${b.text} at (${a.x},${a.y})`);
              }
            }
          }
          // 检查按钮是否在屏幕内
          const outOfScreen = positions.filter(p => p.x < 0 || p.y < 0 || p.x > 1440 || p.y > 900);
          if (outOfScreen.length > 0) {
            issues.push(`ACTION_BTN_OUT_OF_SCREEN: ${outOfScreen.length} buttons`);
          }
        } else if (r.url.includes('/scene/')) {
          // 场景页应该有动作按钮
          // (start-page / case-selector / archive / settings 可能没有)
        }

        // 5. 场景页允许用 meta 副标题代替 h1（用 p.t-overline + p.t-narration）
        if (r.url.includes('/scene/')) {
          const h1s = Array.from(h1Elements);
          const metaYear = document.querySelector('.t-overline');
          const metaLocation = document.querySelector('.t-narration');
          if (h1s.length === 0 && !metaYear) {
            issues.push('NO_H1_OR_META_TITLE');
          }
        }

        return {
          rootText: root?.innerText?.substring(0, 500) || 'EMPTY',
          rootHtmlLen: root?.innerHTML?.length || 0,
          cinematicFrameSize: cinematicFrame ? {
            w: cinematicFrame.getBoundingClientRect().width,
            h: cinematicFrame.getBoundingClientRect().height,
          } : null,
          cinematicAspectSize: cinematicAspect ? {
            w: cinematicAspect.getBoundingClientRect().width,
            h: cinematicAspect.getBoundingClientRect().height,
          } : null,
          bgImage: bgImageEl?.style?.backgroundImage || 'NONE',
          grainOverlayOpacity: grainOverlay ? window.getComputedStyle(grainOverlay).opacity : 'N/A',
          actionBtnCount: actionButtons.length,
          hasInvestigationPanel: !!investigationPanel,
          hasNarration: !!narration,
          hasObserverHint: !!observerHint,
          hasStatusBar: !!sceneStatusBar,
          caseCardCount: caseCard ? 1 : 0,
          h1Count: h1Elements.length,
          bodyBg: window.getComputedStyle(document.body).backgroundColor,
          htmlBg: window.getComputedStyle(document.documentElement).backgroundColor,
          rootBg: root ? window.getComputedStyle(root).backgroundColor : 'N/A',
          issues,
        };
      }, route);

      status = pageInfo.issues.length === 0 ? 'ok' : (pageInfo.issues.some(i => i.startsWith('ROOT_EMPTY') || i.startsWith('CINEMATIC_FRAME')) ? 'fatal' : 'bug');

      if (status === 'ok') report.summary.ok++;
      else if (status === 'fatal') report.summary.fatal++;
      else report.summary.bugs++;

      if (pageInfo.issues.length > 0) {
        console.log(`  ✗ ${pageInfo.issues.length} 个问题:`);
        pageInfo.issues.forEach(i => console.log(`    - ${i}`));
      } else {
        console.log(`  ✓ OK`);
      }
    } catch (err) {
      status = 'fatal';
      pageInfo.issues = [`LOAD_FAILED: ${err.message}`];
      report.summary.fatal++;
      console.log(`  ✗ FATAL: ${err.message}`);
    }

    report.routes.push({
      name: route.name,
      url: route.url,
      case: route.case,
      httpStatus,
      status,
      consoleLogs: consoleLogs.filter(l => l.type === 'error' || l.type === 'warning').slice(0, 10),
      pageErrors,
      failedRequests: failedRequests.slice(0, 10),
      pageInfo,
    });

    await page.close();
  }

  report.endTime = new Date().toISOString();

  // 收集全局 bug
  const allIssues = report.routes.flatMap(r => (r.pageInfo?.issues || []).map(i => ({ route: r.name, issue: i })));
  report.globalBugs = allIssues;

  // 统计
  const issueStats = {};
  for (const { issue } of allIssues) {
    const key = issue.split(':')[0];
    issueStats[key] = (issueStats[key] || 0) + 1;
  }
  report.summary.issueStats = issueStats;

  console.log('\n=== E2E 测试完成 ===');
  console.log(`总路由: ${report.summary.total}`);
  console.log(`OK: ${report.summary.ok}`);
  console.log(`有 bug: ${report.summary.bugs}`);
  console.log(`致命: ${report.summary.fatal}`);
  console.log('\n=== 问题统计 ===');
  for (const [k, v] of Object.entries(issueStats)) {
    console.log(`  ${k}: ${v}`);
  }

  fs.writeFileSync(REPORT_PATH, JSON.stringify(report, null, 2));
  console.log(`\n报告: ${REPORT_PATH}`);

  await browser.close();
})();
