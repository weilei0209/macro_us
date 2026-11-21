// 瀑布图专项自查：截图 + 切换窗口 + 读取口径行 + 捕获报错
const { chromium } = require('playwright-core');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  const errs = [];
  page.on('pageerror', e => errs.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });

  await page.goto('http://127.0.0.1:43187/inflation.html', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);

  const card = page.locator('.chart-card', { has: page.locator('#inf_bei_attr') });
  console.log('note(1m):', await page.locator('#inf_bei_attr-note').innerText());
  console.log('active tab:', await page.locator('.wf-tabs .wf-tab.active').innerText());
  await card.screenshot({ path: process.argv[2] || 'wf_1m.png' });

  await page.locator('.wf-tab[data-key="3m"]').click();
  await page.waitForTimeout(600);
  console.log('note(3m):', await page.locator('#inf_bei_attr-note').innerText());
  console.log('active tab:', await page.locator('.wf-tabs .wf-tab.active').innerText());
  await card.screenshot({ path: process.argv[3] || 'wf_3m.png' });

  // 主题切换后是否仍正常（切到深色再切回）
  await page.locator('.theme-toggle').click();
  await page.waitForTimeout(700);
  const theme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
  const painted = await page.evaluate(() => {
    const c = document.querySelector('#inf_bei_attr canvas');
    if (!c) return false;
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) return true;
    return false;
  });
  console.log('theme after toggle:', theme, '| waterfall painted:', painted);
  await card.screenshot({ path: process.argv[4] || 'wf_dark.png' });
  await page.locator('.theme-toggle').click();

  console.log('errors:', errs.length ? errs : 'none');
  await browser.close();
})();
