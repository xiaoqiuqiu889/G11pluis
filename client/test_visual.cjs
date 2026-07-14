// 真实拉起浏览器自测：拉 localhost:5173 截全屏 + 抓 console
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  const consoleLogs = [];
  page.on('console', msg => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => consoleLogs.push(`[pageerror] ${err.message}`));
  page.on('requestfailed', req => consoleLogs.push(`[requestfailed] ${req.url()} - ${req.failure()?.errorText}`));

  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(2000);

  // 截图
  await page.screenshot({ path: 'D:/G1-ai-native/test_real_screenshot.png', fullPage: true });

  // 检查 root 内容
  const rootText = await page.evaluate(() => document.getElementById('root')?.innerText?.substring(0, 2000) || 'EMPTY');
  const rootHTML = await page.evaluate(() => document.getElementById('root')?.innerHTML?.substring(0, 2000) || 'EMPTY');

  // 检查关键元素
  const h1Text = await page.locator('h1').allInnerTexts();
  const pillarCards = await page.locator('.glass').count();
  const bgImage = await page.evaluate(() => {
    const el = document.querySelector('[style*="background-image"]');
    return el ? el.style.backgroundImage : 'NONE';
  });
  const bgLoaded = await page.evaluate(() => {
    return Array.from(document.images).map(img => `${img.src} - ${img.complete ? 'OK' : 'LOADING'}`).join('\n');
  });

  console.log('=== 真实浏览器自测结果 ===');
  console.log('Console / Errors:');
  consoleLogs.forEach(l => console.log('  ' + l));
  console.log('\n--- Root innerText (前 2000 字符) ---');
  console.log(rootText);
  console.log('\n--- Root innerHTML (前 2000 字符) ---');
  console.log(rootHTML);
  console.log('\n--- h1 元素 ---');
  console.log(JSON.stringify(h1Text));
  console.log('\n--- PillarCard (.glass) 数量 ---');
  console.log(pillarCards);
  console.log('\n--- 背景图 inline style ---');
  console.log(bgImage);
  console.log('\n--- <img> 加载状态 ---');
  console.log(bgLoaded);

  await browser.close();
})();
