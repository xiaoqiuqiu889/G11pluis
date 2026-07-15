// 验证 UP-028 引导灰度：调查高亮 + 11 灰度 + 悬停亮起 + 点过全亮
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  await page.goto('http://localhost:5173/scene/photo_lab_2008', { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(2000);

  // 1. 截图：初始（调查 gateway 高亮 + 11 灰度）
  await page.screenshot({ path: 'D:/G1-ai-native/e2e-screenshots/up028-01-initial.png', fullPage: false, clip: { x: 240, y: 560, width: 960, height: 280 } });

  // 2. dump 12 按钮的 data-lit
  const before = await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button.action-btn[data-type]'));
    return btns.map(b => ({
      type: b.getAttribute('data-type'),
      lit: b.getAttribute('data-lit'),
      gateway: b.getAttribute('data-gateway'),
    }));
  });
  console.log('12 按钮初始 lit 状态:');
  for (const b of before) console.log(`  ${b.type.padEnd(12)} lit=${b.lit} gateway=${b.gateway ?? '-'}`);

  // 3. 悬停 "揭露" → 应该临时全亮
  const revealBtn = page.locator('button.action-btn[data-type="reveal"]').first();
  await revealBtn.hover();
  await page.waitForTimeout(300);
  await page.screenshot({ path: 'D:/G1-ai-native/e2e-screenshots/up028-02-hover-reveal.png', fullPage: false, clip: { x: 240, y: 560, width: 960, height: 280 } });
  const onHover = await revealBtn.getAttribute('data-lit');
  console.log(`\n悬停"揭露"后: data-lit=${onHover}`);

  // 4. 点击"揭露" → 应该点过 + 持久全亮
  await revealBtn.click();
  await page.waitForTimeout(300);
  const onClick = await revealBtn.getAttribute('data-lit');
  console.log(`点击"揭露"后: data-lit=${onClick}`);

  // 取消选择，避免进入提交状态
  await page.evaluate(() => {
    const btn = document.querySelector('button:has-text("取消")');
    if (btn) btn.click();
  }).catch(() => {});

  // 5. 鼠标移开 → "揭露"仍应该全亮（因为已 discovered）
  await page.mouse.move(0, 0);
  await page.waitForTimeout(500);
  const afterLeave = await revealBtn.getAttribute('data-lit');
  console.log(`鼠标移开"揭露"后: data-lit=${afterLeave}`);

  // 6. 截图：发现后（"调查" + "揭露" 亮，10 个灰）
  await page.screenshot({ path: 'D:/G1-ai-native/e2e-screenshots/up028-03-discovered.png', fullPage: false, clip: { x: 240, y: 560, width: 960, height: 280 } });

  console.log('\n结果:');
  console.log(`  gateway (调查) 永远全亮: ${before.find(b => b.type === 'investigate').lit === 'true' ? '✓' : '✗'}`);
  console.log(`  11 个未发现按钮初始灰度: ${before.filter(b => b.type !== 'investigate').every(b => b.lit === 'false') ? '✓' : '✗'}`);
  console.log(`  悬停"揭露"临时全亮: ${onHover === 'true' ? '✓' : '✗'}`);
  console.log(`  点击"揭露"持久全亮: ${onClick === 'true' ? '✓' : '✗'}`);
  console.log(`  鼠标移开后保持全亮: ${afterLeave === 'true' ? '✓' : '✗'}`);

  await browser.close();
})();
