// =============================================================================
// 革命街 AI 原生重构版 · 端到端交互测试（P1 #12）
// -----------------------------------------------------------------------------
// 覆盖"动作按下 → API 调用 → 状态机结算 → UI 更新"端到端链路
// 之前 e2e-suite.cjs 只覆盖页面加载，本测试覆盖核心交互链路
// =============================================================================

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const SCREENSHOT_DIR = 'D:/G1-ai-native/e2e-screenshots';
const REPORT_PATH = 'D:/G1-ai-native/e2e-screenshots/e2e-action-report.json';

const BACKEND = 'http://127.0.0.1:8000';
const FRONTEND = 'http://localhost:5173';

const CASE_01_SCENE = 'photo_lab_2008';
const CASE_02_SCENE = '1985_meeting';

const ACTION_TEST_CASES = [
  // case_01: photo_lab_2008 — 测试 "investigate" 动作
  {
    name: 'case_01-investigate-photo_pair',
    url: `${FRONTEND}/scene/${CASE_01_SCENE}`,
    actorId: 'leila',
    targetId: 'photo_pair',
    expectedApiCall: {
      method: 'POST',
      path: '/v1/runs/',
      bodyContains: { actionType: 'investigate' },
    },
    expectedStateChange: {
      // 调查后，narration 应该变化（不再是默认 narration）
      narrationShouldChange: true,
    },
  },
  // case_01: farewell_2011 — 测试 "give" 动作
  {
    name: 'case_01-give-photo_to_arash',
    url: `${FRONTEND}/scene/farewell_2011`,
    actorId: 'leila',
    targetId: 'arash',
    expectedApiCall: {
      method: 'POST',
      bodyContains: { actionType: 'give' },
    },
  },
  // case_02: 1985_meeting — 测试 "reveal" 动作
  {
    name: 'case_02-reveal-manuscript',
    url: `${FRONTEND}/scene/${CASE_02_SCENE}`,
    actorId: 'natasha_roschina',
    targetId: 'ilya_berman',
    expectedApiCall: {
      method: 'POST',
      bodyContains: { actionType: 'reveal' },
    },
  },
];

(async () => {
  if (!fs.existsSync(SCREENSHOT_DIR)) fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

  console.log('=== G1N E2E Action 端到端测试 ===');
  console.log(`测试用例: ${ACTION_TEST_CASES.length}`);
  console.log('');

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    locale: 'zh-CN',
  });

  const report = {
    startTime: new Date().toISOString(),
    endTime: null,
    summary: { total: ACTION_TEST_CASES.length, ok: 0, partial: 0, fail: 0 },
    cases: [],
    globalBugs: [],
  };

  for (const testCase of ACTION_TEST_CASES) {
    console.log(`\n--- 测试: ${testCase.name} ---`);
    const page = await context.newPage();

    const apiCalls = [];
    const consoleLogs = [];
    const pageErrors = [];

    // 拦截 API 请求
    page.on('request', req => {
      if (req.url().includes('/v1/runs/') && req.method() === 'POST') {
        apiCalls.push({
          method: req.method(),
          url: req.url(),
          body: req.postData(),
          timestamp: new Date().toISOString(),
        });
      }
    });
    page.on('console', msg => consoleLogs.push({ type: msg.type(), text: msg.text() }));
    page.on('pageerror', err => pageErrors.push(err.message));

    let result = { status: 'unknown', checks: {} };

    try {
      // 1. 加载场景
      await page.goto(testCase.url, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(2000);

      // 截图：动作前
      await page.screenshot({ path: path.join(SCREENSHOT_DIR, `e2e-action-${testCase.name}-before.png`), fullPage: true });

      // 2. 找到并点击动作按钮
      const actionButtons = await page.locator('.action-btn').all();
      const initialNarration = await page.evaluate(() => {
        return document.querySelector('.t-narration')?.textContent || '';
      });

      // 寻找包含目标 targetId 名称的 contextActions 按钮（case_01 contextActions）
      // 或者按 actionType 匹配（更通用）
      let actionType = null;
      let pickedActionBtn = null;
      for (const btn of actionButtons) {
        const text = (await btn.textContent()) || '';
        // 跳过"提交"按钮（className 也有 action-btn）
        if (text.includes('提交') || text.includes('·')) continue;
        if (text.includes('调查') || text.includes('揭露') || text.includes('安慰') || text.includes('询问') || text.includes('给出') || text.includes('隐藏') || text.includes('直面') || text.includes('销毁') || text.includes('承诺') || text.includes('等待') || text.includes('离开') || text.includes('沉默')) {
          pickedActionBtn = btn;
          if (text.includes('调查')) actionType = 'investigate';
          else if (text.includes('揭露')) actionType = 'reveal';
          else if (text.includes('询问')) actionType = 'question';
          else if (text.includes('给出')) actionType = 'give';
          else if (text.includes('直面')) actionType = 'confront';
          else if (text.includes('隐藏')) actionType = 'conceal';
          else if (text.includes('安抚')) actionType = 'comfort';
          else if (text.includes('销毁')) actionType = 'destroy';
          else if (text.includes('承诺')) actionType = 'promise';
          else if (text.includes('等待')) actionType = 'wait';
          else if (text.includes('离开')) actionType = 'leave';
          else if (text.includes('沉默')) actionType = 'silence';
          console.log(`  选中动作: ${actionType}`);
          break;
        }
      }
      if (!pickedActionBtn && actionButtons.length > 0) {
        pickedActionBtn = actionButtons[0];
      }

      if (pickedActionBtn) {
        await pickedActionBtn.click();
        await page.waitForTimeout(500);
        // 2.5 找到"提交"按钮（包含动作名 + "提交"）
        // 等待 提交 按钮出现
        const submitBtn = page.locator('button:has-text("提交")').first();
        const submitVisible = await submitBtn.isVisible().catch(() => false);
        if (submitVisible) {
          console.log(`  点击"提交"按钮`);
          await submitBtn.click();
        } else {
          console.log(`  ⚠ 未找到"提交"按钮`);
        }
        // 3. 等待 API 响应 + UI 更新
        await page.waitForTimeout(3000);

        // 截图：动作后
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, `e2e-action-${testCase.name}-after.png`), fullPage: true });

        // 4. 检查 API 调用
        const targetCall = apiCalls.find(c =>
          c.method === testCase.expectedApiCall.method &&
          c.url.includes('/v1/runs/') &&
          c.body &&
          (actionType === null || c.body.includes(`"actionType":"${actionType}"`))
        );

        result.checks.apiCallFired = !!targetCall;
        result.checks.actionType = actionType;
        if (targetCall) {
          result.checks.apiCallUrl = targetCall.url;
          result.checks.apiCallBody = targetCall.body.substring(0, 300);
        }

        // 5. 检查 UI 更新（narration 变化）
        const afterNarration = await page.evaluate(() => {
          return document.querySelector('.t-narration')?.textContent || '';
        });
        result.checks.narrationChanged = initialNarration !== afterNarration;
        result.checks.narrationBefore = initialNarration.substring(0, 100);
        result.checks.narrationAfter = afterNarration.substring(0, 100);

        // 6. 状态：综合判断
        if (result.checks.apiCallFired && result.checks.narrationChanged) {
          result.status = 'ok';
          report.summary.ok++;
        } else if (result.checks.apiCallFired || result.checks.narrationChanged) {
          result.status = 'partial';
          report.summary.partial++;
        } else {
          result.status = 'fail';
          report.summary.fail++;
        }
      } else {
        result.status = 'fail-no-button';
        result.checks.error = 'no action button found';
        report.summary.fail++;
      }
    } catch (err) {
      result.status = 'error';
      result.checks.error = err.message;
      report.summary.fail++;
      console.log(`  ✗ ERROR: ${err.message}`);
    }

    if (result.checks.apiCallFired) {
      console.log(`  ✓ API 调用触发: ${result.checks.apiCallUrl}`);
    } else {
      console.log(`  ✗ API 调用未触发 (共 ${apiCalls.length} 次 API 调用)`);
    }
    if (result.checks.narrationChanged) {
      console.log(`  ✓ UI 更新（narration 变化）`);
    } else {
      console.log(`  ✗ UI 未更新`);
    }

    report.cases.push({
      name: testCase.name,
      url: testCase.url,
      status: result.status,
      apiCallCount: apiCalls.length,
      ...result.checks,
      pageErrors,
      consoleLogs: consoleLogs.filter(l => l.type === 'error').slice(0, 5),
    });

    await page.close();
  }

  report.endTime = new Date().toISOString();
  fs.writeFileSync(REPORT_PATH, JSON.stringify(report, null, 2));

  console.log('\n=== E2E Action 测试完成 ===');
  console.log(`总用例: ${report.summary.total}`);
  console.log(`OK: ${report.summary.ok}`);
  console.log(`部分: ${report.summary.partial}`);
  console.log(`失败: ${report.summary.fail}`);
  console.log(`\n报告: ${REPORT_PATH}`);

  await browser.close();
})();
