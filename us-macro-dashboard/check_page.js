// 前端自查工具：用 playwright 打开看板页面，检测图表是否渲染 + 捕获 JS 报错。
// 用法：
//   node check_page.js                     # 检查默认几个关键页面
//   node check_page.js <url>               # 检查单个页面
//   node check_page.js <url> <截图路径>     # 检查单个页面并截图
//
// 改完 charts.js / render.py 等影响前端的代码后，先跑一遍再交付。

const { chromium } = require('playwright-core');

const DEFAULT_PAGES = [
  'index.html',
  'employment.html',
  'inflation.html',
  'growth.html',
  'fiscal.html',
  'monetary.html',
  'leading.html',
];

async function checkPage(browser, url, shotPath) {
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(`[console.error] ${msg.text()}`);
  });
  page.on('pageerror', err => errors.push(`[pageerror] ${err.message}\n${err.stack || ''}`));

  await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(1500);

  const result = await page.evaluate(() => {
    const boxes = document.querySelectorAll('.chart-box');
    const info = [];
    boxes.forEach(box => {
      const canvases = box.querySelectorAll('canvas');
      let hasContent = false;
      if (canvases.length > 0) {
        const c = canvases[0];
        try {
          const ctx = c.getContext('2d');
          const data = ctx.getImageData(0, 0, c.width, c.height).data;
          for (let i = 3; i < data.length; i += 4) {
            if (data[i] !== 0) { hasContent = true; break; }
          }
        } catch (e) { hasContent = true; }
      }
      info.push({ id: box.id, ok: hasContent });
    });
    return info;
  });

  if (shotPath) await page.screenshot({ path: shotPath, fullPage: true });
  await page.close();

  const bad = result.filter(r => !r.ok).map(r => r.id);
  return { url, total: result.length, bad, errors };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const arg = process.argv[2];
  let pages, shotDir = null;

  if (arg && /^https?:\/\//.test(arg)) {
    pages = [arg];
    if (process.argv[3]) shotDir = process.argv[3];
  } else {
    const base = 'http://127.0.0.1:43187/';
    pages = DEFAULT_PAGES.map(p => base + p);
  }

  let allPass = true;
  for (const url of pages) {
    const shotPath = shotDir ? shotDir : null;
    const r = await checkPage(browser, url, shotPath);
    const ok = r.bad.length === 0 && r.errors.length === 0;
    if (!ok) allPass = false;
    console.log(`${ok ? '✅' : '❌'} ${url.replace('http://127.0.0.1:43187/', '')}  (图表 ${r.total} 个, 空白 ${r.bad.length} 个, 报错 ${r.errors.length} 条)`);
    if (r.bad.length) console.log(`    空白图表: ${r.bad.join(', ')}`);
    if (r.errors.length) r.errors.forEach(e => console.log(`    ${e.split('\n')[0]}`));
  }

  await browser.close();
  console.log(allPass ? '\n全部通过' : '\n存在失败项，需修复');
  process.exit(allPass ? 0 : 1);
})();
