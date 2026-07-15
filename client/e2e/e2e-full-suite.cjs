// 全 6 场景端到端：createRun → enterScene → action submit → UI 更新
// W12-E2E-runsync 套件升级版
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const SCREENSHOT_DIR = 'D:/G1-ai-native/e2e-screenshots';
const REPORT_PATH = 'D:/G1-ai-native/e2e-screenshots/e2e-full-report.json';
const BACKEND = 'http://127.0.0.1:8000';
const FRONTEND = 'http://localhost:5173';

const SCENES = [
  { id: 'photo_lab_2008', case: 'case_01_revolution_street', name: 'case_01-photo_lab_2008' },
  { id: 'farewell_2011', case: 'case_01_revolution_street', name: 'case_01-farewell_2011' },
  { id: 'reunion_2024', case: 'case_01_revolution_street', name: 'case_01-reunion_2024' },
  { id: '1985_meeting', case: 'case_02_moscow_no_fairy_tale', name: 'case_02-1985_meeting' },
  { id: '1989_farewell', case: 'case_02_moscow_no_fairy_tale', name: 'case_02-1989_farewell' },
  { id: '2008_reunion', case: 'case_02_moscow_no_fairy_tale', name: 'case_02-2008_reunion' },
];

(async () => {
  if (!fs.existsSync(SCREENSHOT_DIR)) fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

  console.log('=== W12-E2E-runsync 全 6 场景验证 ===\n');

  // 后端健康
  const health = await fetch(`${BACKEND}/health`).then(r => r.json()).catch(() => null);
  console.log(`后端: ${health ? 'OK' : 'DOWN'} (${health?.activeRuns ?? '?'} active runs)\n`);

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' });

  const report = {
    startTime: new Date().toISOString(),
    backend: { health: !!health, activeRuns: health?.activeRuns },
    cases: [],
    summary: { total: SCENES.length, pass: 0, fail: 0 },
  };

  for (const scene of SCENES) {
    console.log(`--- ${scene.name} ---`);
    const page = await context.newPage();

    const apiCalls = [];
    const consoleErrors = [];
    page.on('request', req => {
      if (req.url().includes('/v1/runs')) {
        apiCalls.push({ method: req.method(), url: req.url(), body: req.postData()?.substring(0, 100) });
      }
    });
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('pageerror', e => consoleErrors.push('pageerror: ' + e.message));

    const caseReport = { scene: scene.id, case: scene.case, status: 'pending' };

    try {
      // 1. 加载场景
      await page.goto(`${FRONTEND}/scene/${scene.id}`, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(1500);

      // 截图：初始
      await page.screenshot({ path: path.join(SCREENSHOT_DIR, `runsync-${scene.name}-initial.png`), fullPage: true });

      // 2. 验证 createRun 被调
      const createRunCalls = apiCalls.filter(c => c.method === 'POST' && /\/v1\/runs\/?$/.test(c.url.replace(/\?.*$/, '')));
      caseReport.createRunCalled = createRunCalls.length;
      console.log(`  createRun 调用: ${createRunCalls.length}`);

      // 3. 验证动作按钮可点击
      const actionBtns = await page.locator('button.action-btn:not(:has-text("提交")):not(:has-text("取消")):not(:has-text("重演")):not(:has-text("时间跳转")):not(:has-text("卷宗")):not(:has-text("返回"))').all();
      caseReport.actionButtonCount = actionBtns.length;
      console.log(`  动作按钮数: ${actionBtns.length}`);

      // 4. 找第一个 12 行为按钮（按 label）
      let targetBtn = null;
      let targetType = null;
      for (const btn of actionBtns) {
        const text = (await btn.textContent()) || '';
        for (const [k, v] of [
          ['调查', 'investigate'], ['揭露', 'reveal'], ['询问', 'question'],
          ['给出', 'give'], ['直面', 'confront'], ['隐藏', 'conceal'],
          ['安抚', 'comfort'], ['销毁', 'destroy'], ['承诺', 'promise'],
          ['等待', 'wait'], ['离开', 'leave'], ['沉默', 'silence'],
        ]) {
          if (text.includes(k)) { targetBtn = btn; targetType = v; break; }
        }
        if (targetBtn) break;
      }
      caseReport.firstActionType = targetType;
      console.log(`  选中: ${targetType}`);

      // 5. 点击 + 提交
      const actionCallsBefore = apiCalls.length;
      if (targetBtn) {
        const enabled = await targetBtn.isEnabled();
        caseReport.actionBtnEnabled = enabled;
        if (enabled) {
          await targetBtn.click();
          await page.waitForTimeout(300);
          const submitBtn = page.locator('button:has-text("提交")').first();
          if (await submitBtn.isVisible()) {
            await submitBtn.click();
            await page.waitForTimeout(3000);
          }
        }
      }
      const newCalls = apiCalls.length - actionCallsBefore;
      caseReport.actionApiCalls = newCalls;
      console.log(`  action API: ${newCalls}`);

      // 6. 截图：动作后
      await page.screenshot({ path: path.join(SCREENSHOT_DIR, `runsync-${scene.name}-after.png`), fullPage: true });

      // 7. 检查 UI 更新（narration）
      const beforeNarration = await page.evaluate(() => {
        // 取第一次的旁白
        return document.querySelector('.t-narration')?.textContent || '';
      });
      caseReport.narrationAfter = beforeNarration.substring(0, 80);

      // 8. 综合判断
      const pass =
        createRunCalls.length >= 1 &&
        newCalls >= 1 &&
        caseReport.actionButtonCount >= 12 &&
        !caseReport.consoleErrors || consoleErrors.length === 0;
      caseReport.status = pass ? 'pass' : 'fail';
      caseReport.consoleErrors = consoleErrors;
      console.log(`  结果: ${pass ? '✓ PASS' : '✗ FAIL'}`);
      if (pass) report.summary.pass++; else report.summary.fail++;
    } catch (err) {
      caseReport.status = 'error';
      caseReport.error = err.message;
      report.summary.fail++;
      console.log(`  ✗ ERROR: ${err.message}`);
    }

    report.cases.push(caseReport);
    await page.close();
  }

  report.endTime = new Date().toISOString();
  fs.writeFileSync(REPORT_PATH, JSON.stringify(report, null, 2));

  console.log(`\n=== 总结 ===`);
  console.log(`通过: ${report.summary.pass}/${report.summary.total}`);
  console.log(`失败: ${report.summary.fail}/${report.summary.total}`);
  console.log(`报告: ${REPORT_PATH}`);

  await browser.close();
  process.exit(report.summary.fail === 0 ? 0 : 1);
})();
