const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  // 截 h1 元素本身
  const h1 = page.locator('h1').first();
  await h1.screenshot({ path: 'D:/G1-ai-native/test_h1.png' });

  // 截 .cinematic-frame 元素本身
  const cf = page.locator('.cinematic-frame').first();
  await cf.screenshot({ path: 'D:/G1-ai-native/test_cf.png' });

  // 截 PillarCard 第一个
  const pc = page.locator('.glass').first();
  await pc.screenshot({ path: 'D:/G1-ai-native/test_pc.png' });

  // 关键：取 h1 的实际像素颜色（不是 computed style）
  const h1Bg = await h1.evaluate((el) => {
    // 看 h1 像素颜色 - 使用 canvas
    return new Promise(resolve => {
      const canvas = document.createElement('canvas');
      canvas.width = el.offsetWidth;
      canvas.height = el.offsetHeight;
      // html2canvas 太复杂，用另一种方法：直接读 CSS 可见祖先
      const ancestors = [];
      let cur = el;
      while (cur && cur !== document.body) {
        const s = getComputedStyle(cur);
        ancestors.push({
          tag: cur.tagName,
          class: cur.className?.substring?.(0, 80),
          opacity: s.opacity,
          visibility: s.visibility,
          display: s.display,
          overflow: s.overflow,
          background: s.background.substring(0, 80),
          color: s.color,
          zIndex: s.zIndex
        });
        cur = cur.parentElement;
      }
      resolve(ancestors);
    });
  });
  console.log('H1 祖先链:');
  h1Bg.forEach((a, i) => console.log(`  ${i}: ${a.tag}.${a.class} opacity=${a.opacity} vis=${a.visibility} display=${a.display} bg=${a.background} z=${a.zIndex}`));

  await browser.close();
})();
