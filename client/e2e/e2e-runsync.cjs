// 端到端：runId 创建 → action 提交 → UI 更新（VITE_USE_MOCK=false 真后端模式）
// 验证 W12-E2E-runsync 修复
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const SCREENSHOT_DIR = 'D:/G1-ai-native/e2e-screenshots';
const REPORT_PATH = 'D:/G1-ai-native/e2e-screenshots/e2e-runsync-report.json';

const BACKEND = 'http://127.0.0.1:8000';
const FRONTEND = 'http://localhost:5173';

(async () => {
  if (!fs.existsSync(SCREENSHOT_DIR)) fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

  console.log('=== W12-E2E-runsync 验证 ===\n');

  // 1. 后端健康检查
  const health = await fetch(`${BACKEND}/health`).then(r => r.json()).catch(e => ({ error: e.message }));
  console.log('后端健康:', JSON.stringify(health));

  // 2. 先直调 createRun 验证后端
  const createResp = await fetch(`${BACKEND}/v1/runs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ caseSlug: 'case_01_revolution_street', startSceneId: 'photo_lab_2008' }),
  }).then(r => r.json()).catch(e => ({ error: e.message }));
  console.log('createRun 直调:', JSON.stringify(createResp).substring(0, 200));
  const serverRunId = createResp.run?.runId;

  // 3. 加载浏览器 + 验证前端能跑通
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  const apiCalls = [];
  const consoleErrors = [];
  page.on('request', req => {
    if (req.url().includes('/v1/runs') && req.method() === 'POST') {
      apiCalls.push({ url: req.url(), body: req.postData() });
    }
  });
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', e => consoleErrors.push('pageerror: ' + e.message));

  console.log('\n--- 加载 /scene/photo_lab_2008 ---');
  await page.goto(`${FRONTEND}/scene/photo_lab_2008`, { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'runsync-01-initial.png'), fullPage: true });

  // 4. 验证 runId 已经被服务端注册
  const createRunCalls = apiCalls.filter(c => c.url.endsWith('/v1/runs') || /\/v1\/runs\?/.test(c.url));
  console.log(`createRun 调用次数: ${createRunCalls.length}`);

  // 5. 拿到客户端的 runId 并验证服务端能找到
  const clientRunId = await page.evaluate(() => {
    return localStorage.getItem('g1n.runId') || null;
  });
  // 如果 zustand 持久化，localStorage 可能有；否则从 store 读
  const fromStore = await page.evaluate(() => {
    return window.__store?.getState?.()?.runId || null;
  });
  console.log('客户端 runId (localStorage):', clientRunId);
  console.log('客户端 runId (store):', fromStore);

  // 6. 尝试点击动作 → 提交
  const actionBefore = apiCalls.length;
  const investigateBtn = page.locator('button.action-btn:has-text("调查")').first();
  if (await investigateBtn.count() > 0) {
    const enabled = await investigateBtn.isEnabled();
    console.log('调查按钮启用:', enabled);
    if (enabled) {
      await investigateBtn.click();
      await page.waitForTimeout(500);
      // 点"提交"
      const submitBtn = page.locator('button:has-text("提交")').first();
      if (await submitBtn.isVisible()) {
        await submitBtn.click();
        await page.waitForTimeout(3000);
      }
    }
  }
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'runsync-02-after-action.png'), fullPage: true });

  const newActionCalls = apiCalls.length - actionBefore;
  console.log(`action 提交后新增 API 调用: ${newActionCalls}`);

  // 7. 看是否有错误 toast
  const errorToast = await page.evaluate(() => {
    const el = document.querySelector('[role="alert"], .error-toast, .toast-error, .bg-red-500\\/40');
    return el ? el.textContent?.substring(0, 200) : null;
  });
  console.log('错误 toast:', errorToast);

  // 8. 输出报告
  const report = {
    timestamp: new Date().toISOString(),
    backendHealth: health,
    createRunDirect: !!serverRunId,
    createRunApiCalls: createRunCalls.length,
    actionSubmitApiCalls: newActionCalls,
    consoleErrors,
    pass:
      !!serverRunId &&
      createRunCalls.length >= 1 &&
      newActionCalls >= 1 &&
      !errorToast,
  };
  fs.writeFileSync(REPORT_PATH, JSON.stringify(report, null, 2));
  console.log('\n=== 报告 ===');
  console.log(JSON.stringify(report, null, 2));
  console.log(`\n结果: ${report.pass ? '✓ PASS' : '✗ FAIL'}`);

  await browser.close();
  process.exit(report.pass ? 0 : 1);
})();
