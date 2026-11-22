// 瀑布图专项自查：截图 + 逐个切换窗口 + 读取口径行 + 主题切换后校验 + 捕获报错
// 用法：
//   node check_wf.js                                   # 默认查通胀页 BEI 归因
//   node check_wf.js fiscal.html fis_acm_attr          # 查财政页 ACM 归因
//   node check_wf.js fiscal.html fis_acm_attr 43187    # 指定端口
const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const pageFile = process.argv[2] || 'inflation.html';
const chartId = process.argv[3] || 'inf_bei_attr';
const port = process.argv[4] || 43187;
// 截图落在 logs/wf/（logs/ 已 gitignore），避免污染仓库根目录
const OUT = path.join(__dirname, 'logs', 'wf');
fs.mkdirSync(OUT, { recursive: true });
const shot = name => path.join(OUT, name);

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 2 });
  const errs = [];
  page.on('pageerror', e => errs.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });

  await page.goto(`http://127.0.0.1:${port}/${pageFile}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);

  const card = page.locator('.chart-card', { has: page.locator(`#${chartId}`) });
  const tabs = page.locator(`.wf-tabs[data-target="${chartId}"] .wf-tab`);
  const n = await tabs.count();
  console.log(`${pageFile} #${chartId}: ${n} 个窗口按钮`);

  for (let i = 0; i < n; i++) {
    const t = tabs.nth(i);
    const key = await t.getAttribute('data-key');
    await t.click();
    await page.waitForTimeout(450);
    const note = await page.locator(`#${chartId}-note`).innerText();
    console.log(`  [${key}] ${note}`);
    await card.screenshot({ path: shot(`wf_${chartId}_${key}.png`) });
  }

  // 主题切换后是否仍正常（切换会触发全量重绘）
  await page.locator('.theme-toggle').click();
  await page.waitForTimeout(800);
  const theme = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
  const painted = await page.evaluate(id => {
    const c = document.querySelector(`#${id} canvas`);
    if (!c) return false;
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) return true;
    return false;
  }, chartId);
  console.log(`主题切换后 theme=${theme} | 瀑布图已绘制=${painted}`);
  await card.screenshot({ path: shot(`wf_${chartId}_theme.png`) });
  await page.locator('.theme-toggle').click();

  console.log('errors:', errs.length ? errs : 'none');
  await browser.close();
})();
