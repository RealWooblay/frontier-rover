import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';

const require = createRequire(import.meta.url);
const { chromium } = require('/Users/jackcoleman/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.dirname(fileURLToPath(import.meta.url));
const { control, vision, weightStep } = require(path.join(root, 'lesson-labs.js'));
const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} != ${expected}`);
near(control(5, 100).left, 0.5);
near(control(5, 100).right, 0.3);
near(control(15, 100).applied, -0.2);
assert.equal(control(15, 100).saturated, true);
assert.equal(control(5, 500).stale, false);
assert.equal(control(5, 501).left, 0);
near(control(-3, 100).left, 0.34);
near(control(-3, 100).right, 0.46);
near(control(5, 100, false).left, 0.4);
assert.throws(() => control(NaN, 0));
near(vision(480).error, 0.5);
near(vision(320).error, 0);
near(vision(160).error, -0.5);
near(weightStep(0.2).nextWeight, 0.22);
near(weightStep(0.2).nextLoss, 0.0361);
near(weightStep(0.6).loss, 0);
near(weightStep(0.2, 0.5).nextLoss, 0.0225);
const url = pathToFileURL(path.join(root, 'study.html')).href;
const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844], ['narrow', 320, 720]]) {
    const page = await browser.newPage({ viewport: { width, height } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(url);
    await page.waitForSelector('#lc-left');
    async function range(selector, value) {
      await page.locator(selector).evaluate((element, value) => {
        element.value = String(value);
        element.dispatchEvent(new Event('input', { bubbles: true }));
      }, value);
    }
    assert.equal(await page.locator('#lc-left').innerText(), '50%');
    assert.equal(await page.locator('#lc-right').innerText(), '30%');
    await page.locator('#lc-feedback').uncheck();
    assert.equal(await page.locator('#lc-left').innerText(), '40%');
    await page.locator('#lc-feedback').check();
    await range('#lc-heading', 15);
    assert.equal(await page.locator('#lc-left').innerText(), '60%');
    assert.match(await page.locator('#lc-result').innerText(), /Saturation/);
    await range('#lc-age', 900);
    assert.equal(await page.locator('#lc-right').innerText(), '0%');
    assert.match(await page.locator('#lc-result').innerText(), /Timeout/);
    await page.locator('#lc-reset').click();
    await page.locator('[data-lab="control"]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(root, `control-${name}.png`) });
    await range('#lv-center', 320);
    assert.match(await page.locator('#lv-result').innerText(), /Centred/);
    assert.equal(await page.locator('#lv-box').getAttribute('x'), '280');
    await range('#lv-center', 160);
    assert.match(await page.locator('#lv-result').innerText(), /-0.500/);
    await range('#lv-center', 480);
    await range('#lw-weight', 0.6);
    assert.equal(await page.locator('#lw-loss').innerText(), '0.000000');
    await page.locator('#lw-reset').click();
    await page.locator('#lw-step').click();
    assert.equal(await page.locator('#lw-weight-value').innerText(), '0.220000');
    assert.equal(await page.locator('#lw-loss').innerText(), '0.036100');
    await page.locator('[data-lab="weight"]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(root, `weight-${name}.png`) });
    await page.locator('#lw-reset').click();
    const documentCheck = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth > innerWidth,
      images: [...document.images].map(image => ({ src: image.src, loaded: image.naturalWidth > 0 })),
      headings: document.querySelectorAll('main h2').length,
      answers: document.querySelectorAll('details').length,
      badAnchors: [...document.querySelectorAll('a[href^="#"]')].filter(a => !document.getElementById(a.hash.slice(1))).map(a => a.hash),
      localLinks: [...document.querySelectorAll('a[href]')].map(a => a.href).filter(href => href.startsWith('file:')),
    }));
    const missing = documentCheck.localLinks.filter(href => !fs.existsSync(fileURLToPath(new URL(href))));
    if (documentCheck.overflow || errors.length || missing.length || documentCheck.badAnchors.length || documentCheck.images.some(i => !i.loaded)) {
      throw new Error(JSON.stringify({ name, ...documentCheck, missing, errors }));
    }
    await page.locator('h1').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(root, `reader-${name}.png`) });
    const answer = page.locator('details').first();
    await answer.locator('summary').click();
    if (!(await answer.getAttribute('open') === '')) throw new Error('Answer did not open');
    if (!(await answer.innerText()).includes('stale_frame')) throw new Error('Missing answer content');
    await page.locator('img').last().scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(root, `evidence-${name}.png`) });
    results.push({ name, width, height, errors, missing, ...documentCheck });
    await page.close();
  }
} finally {
  await browser.close();
}
fs.writeFileSync(path.join(root, 'reader-verification.json'), JSON.stringify(results, null, 2));
console.log(JSON.stringify(results.map(({ name, headings, answers, overflow, images, errors, missing }) => ({ name, headings, answers, overflow, images, errors, missing })), null, 2));
