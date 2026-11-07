/* Run against the owned recording-only server created by the Python runner. */
const { chromium } = require(process.env.VANTAGE_PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.VANTAGE_BROWSER || '/usr/bin/brave',
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [], failed = [], serverErrors = [];
  page.on('pageerror', error => errors.push(String(error)));
  page.on('requestfailed', request => failed.push({ url: request.url(), failure: request.failure() }));
  page.on('response', response => {
    if (response.status() >= 500) serverErrors.push({ url: response.url(), status: response.status() });
  });
  try {
    await page.goto(process.argv[2], { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.querySelector('#tc-clock')?.textContent.includes(' / '),
      null, { timeout: 60000 });
    const tutorial = page.getByRole('button', { name: 'Skip tutorial', exact: true });
    if (await tutorial.isVisible()) await tutorial.click();
    await page.waitForTimeout(800);
    await page.locator('#tc-play').click();
    await page.waitForTimeout(200);
    const paused = await page.locator('#tc-clock').textContent();
    await page.waitForTimeout(1200);
    const stillPaused = await page.locator('#tc-clock').textContent();
    if (paused !== stillPaused) throw new Error(`Pause failed: ${paused} / ${stillPaused}`);
    const scrub = page.locator('#scrub-canvas');
    const box = await scrub.boundingBox();
    if (!box) throw new Error('Missing seek control');
    await scrub.click({ position: { x: box.width * 0.6, y: box.height / 2 } });
    await page.waitForTimeout(500);
    const sought = await page.locator('#tc-clock').textContent();
    if (sought === paused) throw new Error('Seeking did not change the clock');
    await page.locator('#tc-play').click();
    await page.waitForTimeout(1200);
    const resumed = await page.locator('#tc-clock').textContent();
    if (resumed === sought) throw new Error('Resume did not advance');
    await page.locator('#tc-faster').click();
    const speed = await page.locator('#tc-speed').textContent();
    if (speed === '1×') throw new Error('Speed control did not change');
    await page.screenshot({ path: process.argv[3] });
    if (errors.length || failed.length || serverErrors.length) {
      throw new Error(JSON.stringify({ errors, failed, serverErrors }));
    }
    console.log(JSON.stringify({ passed: true, paused, stillPaused, sought, resumed, speed,
      errors, failed, serverErrors, screenshot: process.argv[3] }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.stack || String(error)); process.exitCode = 1; });
