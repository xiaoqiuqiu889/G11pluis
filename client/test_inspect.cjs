const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  // 1. 抓 main 元素 box + 样式
  const main = await page.evaluate(() => {
    const el = document.querySelector('main');
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return { rect: { x: r.x, y: r.y, w: r.width, h: r.height }, position: s.position, height: s.height, minHeight: s.minHeight, padding: s.padding };
  });
  console.log('MAIN:', JSON.stringify(main, null, 2));

  // 2. 抓 .cinematic-frame box + 样式
  const cf = await page.evaluate(() => {
    const el = document.querySelector('.cinematic-frame');
    if (!el) return { found: false };
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return { found: true, rect: { x: r.x, y: r.y, w: r.width, h: r.height }, position: s.position, height: s.height, overflow: s.overflow, backgroundColor: s.backgroundColor };
  });
  console.log('CINEMATIC-FRAME:', JSON.stringify(cf, null, 2));

  // 3. 抓 .cinematic-aspect box
  const ca = await page.evaluate(() => {
    const el = document.querySelector('.cinematic-aspect');
    if (!el) return { found: false };
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return { found: true, rect: { x: r.x, y: r.y, w: r.width, h: r.height }, position: s.position, display: s.display, alignItems: s.alignItems, justifyContent: s.justifyContent };
  });
  console.log('CINEMATIC-ASPECT:', JSON.stringify(ca, null, 2));

  // 4. 抓 h1
  const h1 = await page.evaluate(() => {
    const el = document.querySelector('h1');
    if (!el) return { found: false };
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return { found: true, text: el.innerText, rect: { x: r.x, y: r.y, w: r.width, h: r.height }, fontSize: s.fontSize, color: s.color, opacity: s.opacity, visibility: s.visibility, display: s.display, zIndex: s.zIndex };
  });
  console.log('H1:', JSON.stringify(h1, null, 2));

  // 5. 抓 PillarCard
  const pc = await page.evaluate(() => {
    const el = document.querySelector('.glass');
    if (!el) return { found: false };
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return { found: true, rect: { x: r.x, y: r.y, w: r.width, h: r.height }, color: s.color, opacity: s.opacity, visibility: s.visibility, display: s.display, background: s.background, border: s.border };
  });
  console.log('PILLARCARD:', JSON.stringify(pc, null, 2));

  // 6. 抓背景图 div
  const bg = await page.evaluate(() => {
    const el = document.querySelector('[style*="background-image"]');
    if (!el) return { found: false };
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return { found: true, rect: { x: r.x, y: r.y, w: r.width, h: r.height }, backgroundImage: s.backgroundImage, position: s.position };
  });
  console.log('BG-IMAGE-DIV:', JSON.stringify(bg, null, 2));

  await browser.close();
})();
