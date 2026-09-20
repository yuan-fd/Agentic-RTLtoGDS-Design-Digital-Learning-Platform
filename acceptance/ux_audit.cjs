const fs = require('fs');
const path = require('path');
const playwrightModule = process.env.PLAYWRIGHT_NODE_MODULES || 'playwright';
const { chromium } = require(playwrightModule.endsWith('/node_modules') ? `${playwrightModule}/playwright` : playwrightModule);

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
    const workflowPage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    workflowPage.on('console', message => {
      const item = { width: 1440, type: message.type(), text: message.text(), workflow: true };
      consoleLog.push(item);
      if (message.type() === 'error' || message.type() === 'warning') {
        report.push({ check: 'workflow-console', status: 'FAIL', detail: message.text() });
      }
    });
    workflowPage.on('response', response => networkLog.push({ width: 1440, status: response.status(), url: response.url(), workflow: true }));
    await workflowPage.goto(url, { waitUntil: 'networkidle' });
    if (!process.env.UX_FULL_FLOW) {
      report.push({ check: 'authenticated-workflow', status: 'BLOCKED', detail: 'set UX_FULL_FLOW=1 with V2_USERNAME and V2_PASSWORD to run the independent workflow' });
    } else if (!process.env.V2_USERNAME || !process.env.V2_PASSWORD) {
      report.push({ check: 'authenticated-workflow', status: 'BLOCKED', detail: 'V2_USERNAME and V2_PASSWORD are required' });
    } else {
      await workflowPage.fill('#usernameInput', process.env.V2_USERNAME);
      await workflowPage.fill('#passwordInput', process.env.V2_PASSWORD);
      await workflowPage.click('#loginForm button[type="submit"]');
      await workflowPage.waitForFunction(() => document.querySelector('#loginForm').hidden, null, { timeout: 120000 });
      report.push({ check: 'login', status: 'PASS', detail: 'v2 session established through the M1 UI' });

      await workflowPage.fill('#specInput', 'a digital circuit');
      await workflowPage.click('#freezeButton');
      await workflowPage.waitForFunction(() => Boolean(document.querySelector('#clarificationQuestions').textContent.trim()), null, { timeout: 120000 });
      report.push({ check: 'clarification', status: 'PASS', detail: 'incomplete natural-language input produced clarification questions' });

      await workflowPage.fill('#specInput', 'An 8-bit synchronous counter named counter with clk, active-low synchronous reset rst_n, enable, and 8-bit output q. On each rising clock edge, reset has priority and sets q to zero; otherwise enable increments q modulo 256 and disabled enable holds q. Use a 5 ns clock period.');
      await workflowPage.click('#freezeButton');
      await workflowPage.waitForFunction(() => document.querySelector('#freezeButton').textContent.includes('Freeze'), null, { timeout: 120000 });
      report.push({ check: 'spec-assessment', status: 'PASS', detail: 'complete SpecIR was assessed' });
      await workflowPage.click('#freezeButton');
      await workflowPage.waitForFunction(() => !document.querySelector('#generateButton').disabled, null, { timeout: 30000 });
      report.push({ check: 'freeze', status: 'PASS', detail: 'SpecIR was frozen before generation' });

      await workflowPage.click('#generateButton');
      await workflowPage.waitForFunction(() => document.querySelector('#rtlEditor').value.trim().length > 0, null, { timeout: 180000 });
      report.push({ check: 'rtl-generation', status: 'PASS', detail: 'Direct LLM produced an RTL version' });
      await workflowPage.click('#verifyButton');
      await workflowPage.waitForFunction(() => ['✓', '×'].includes(document.querySelector('#compileMark').textContent), null, { timeout: 180000 });
      const verified = await workflowPage.locator('#compileMark').textContent() === '✓';
      report.push({ check: 'verification', status: verified ? 'PASS' : 'FAIL', detail: verified ? 'compile/lint passed' : 'compile/lint failed' });
      if (!verified) throw new Error('verification failed in the independent workflow');
      await workflowPage.click('#simulateButton');
      await workflowPage.waitForFunction(() => ['✓', '×'].includes(document.querySelector('#simulationMark').textContent), null, { timeout: 180000 });
      const simulated = await workflowPage.locator('#simulationMark').textContent() === '✓';
      report.push({ check: 'simulation', status: simulated ? 'PASS' : 'FAIL', detail: simulated ? 'frozen oracle simulation passed' : 'simulation failed' });
      if (!simulated) throw new Error('simulation failed in the independent workflow');
      await workflowPage.click('#workbenchTab');
      await workflowPage.waitForFunction(() => !document.querySelector('#gdsButton').disabled, null, { timeout: 30000 });
      await workflowPage.click('#gdsButton');
      await workflowPage.waitForFunction(() => document.querySelector('#evidenceMetadata').textContent.includes('"status": "succeeded"') || document.querySelector('#evidenceMessage').textContent.includes('gds_incomplete'), null, { timeout: 900000 });
      const evidence = await workflowPage.locator('#evidenceMetadata').textContent();
      const gdsPassed = evidence.includes('"status": "succeeded"') && await workflowPage.locator('#layoutStatus').textContent().then(value => value.startsWith('Rendered'));
      report.push({ check: 'gds-evidence', status: gdsPassed ? 'PASS' : 'FAIL', detail: gdsPassed ? 'Nangate45 evidence and layout preview are available' : evidence || 'GDS evidence is incomplete' });
      if (gdsPassed) {
        const artifactRows = await workflowPage.locator('#artifactList li').evaluateAll(rows => rows.map(row => ({
          kind: row.firstElementChild && row.firstElementChild.textContent,
          sha256: row.lastElementChild && row.lastElementChild.textContent,
        })));
        const runId = (await workflowPage.locator('#runState').textContent()).split(':', 1)[0];
        fs.writeFileSync(path.join(output, 'artifact-manifest.json'), JSON.stringify({
          source: 'independent authenticated browser workflow',
          run_id: runId,
          evidence: JSON.parse(evidence),
          artifacts: artifactRows,
        }, null, 2) + '\n');
      }
    }
    await workflowPage.close();
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
