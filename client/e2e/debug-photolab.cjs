// 快速调试：加载 photo_lab_2008，截图 + dump 关键 DOM
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  console.log('--- loading /scene/photo_lab_2008 ---');
  await page.goto('http://localhost:5173/scene/photo_lab_2008', { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(2000);

  // 截图
  await page.screenshot({ path: 'D:/G1-ai-native/e2e-screenshots/debug-photolab.png', fullPage: true });
  console.log('截图保存: debug-photolab.png');

  // 检查 action bar 位置
  const actionBar = await page.evaluate(() => {
    const el = document.querySelector('[aria-label="行为栏"]');
    if (!el) return { found: false };
    const rect = el.getBoundingClientRect();
    const styles = window.getComputedStyle(el);
    return {
      found: true,
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      position: styles.position,
      top: styles.top, bottom: styles.bottom,
      parent: el.parentElement?.className,
    };
  });
  console.log('Action bar:', JSON.stringify(actionBar, null, 2));

  // 检查背景图
  const bg = await page.evaluate(() => {
    const el = document.querySelector('.cinematic-frame > div[style*="background-image"]');
    if (!el) return { found: false };
    return { found: true, bg: el.style.backgroundImage, classes: el.className };
  });
  console.log('背景图:', JSON.stringify(bg, null, 2));

  // 检查 action buttons 内容
  const buttons = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('button.action-btn')).slice(0, 14).map(b => ({
      text: b.textContent?.trim().substring(0, 30),
      type: b.getAttribute('data-type'),
      active: b.getAttribute('data-active'),
    }));
  });
  console.log('按钮:', JSON.stringify(buttons, null, 2));

  // meta header 位置
  const meta = await page.evaluate(() => {
    const el = document.querySelector('.cinematic-frame .t-overline.text-amber-glow');
    if (!el) return { found: false };
    const rect = el.getBoundingClientRect();
    return { found: true, text: el.textContent, x: rect.x, y: rect.y, w: rect.width, h: rect.height };
  });
  console.log('Meta:', JSON.stringify(meta, null, 2));

  console.log('\n--- errors ---');
  for (const e of errors) console.log(e);

  await browser.close();
})();
