const fs = require('fs');
const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT_NODE_MODULES || 'playwright');

const output = process.env.ACCEPTANCE_OUTPUT || path.join(process.cwd(), 'acceptance', 'reports');
const url = process.env.M1_URL || 'http://127.0.0.1:8101';
fs.mkdirSync(path.join(output, 'browser-screenshots'), { recursive: true });

(async () => {
  const report = [];
  const consoleLog = [];
  const networkLog = [];
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE });
    for (const width of [320, 768, 1024, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      page.on('console', message => {
        const item = { width, type: message.type(), text: message.text() };
        consoleLog.push(item);
        if (message.type() === 'error' || message.type() === 'warning') report.push({ check: `console-${width}`, status: 'FAIL', detail: message.text() });
      });
      page.on('response', response => networkLog.push({ width, status: response.status(), url: response.url() }));
      await page.goto(url, { waitUntil: 'networkidle' });
      await page.screenshot({ path: path.join(output, 'browser-screenshots', `m1-${width}.png`), fullPage: true });
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      report.push({ check: `viewport-${width}`, status: overflow ? 'FAIL' : 'PASS', detail: overflow ? 'horizontal overflow' : 'layout fits viewport' });
      report.push({ check: `catalog-${width}`, status: (await page.locator('#courseCatalog li').count()) === 10 ? 'PASS' : 'FAIL', detail: 'Course Lab entries' });
      await page.close();
    }
  } catch (error) {
    report.push({ check: 'browser-runtime', status: 'BLOCKED', detail: String(error) });
  } finally {
    if (browser) await browser.close();
  }
  fs.writeFileSync(path.join(output, 'console-log.json'), JSON.stringify(consoleLog, null, 2));
  fs.writeFileSync(path.join(output, 'network-log.json'), JSON.stringify(networkLog, null, 2));
  fs.writeFileSync(path.join(output, 'ux-report.json'), JSON.stringify(report, null, 2));
  process.exitCode = report.some(item => item.status === 'FAIL' || item.status === 'BLOCKED') ? 1 : 0;
})();
