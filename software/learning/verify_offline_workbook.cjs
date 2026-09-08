const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 900}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.context().setOffline(true);
    const file = process.argv[2] || path.join(__dirname, 'offline_workbook.html');
    await page.goto(pathToFileURL(file).href);
    await page.waitForFunction(() => window.ROVER_EVIDENCE && window.roverInfer);
    const diff = await page.evaluate(() => {
      const e = window.ROVER_EVIDENCE;
      return Math.max(...window.roverInfer(e.model_test.input).o.map((v,i) => Math.abs(v-e.model_test.output[i])));
    });
    assert(diff < 1e-12, 'Browser model differs from NumPy reference');
    const out = '/private/tmp/frontier-workbook-qa';
    fs.mkdirSync(out, {recursive:true});
    for (const width of [1280,360]) {
      await page.setViewportSize({width, height:900});
      for (const name of ['system','vision','weights','fit','replay','next']) {
        await page.locator('#tab-'+name).click();
        assert(await page.locator('#'+name).isVisible());
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth+1);
        assert(!overflow, 'Horizontal overflow in '+name+' at '+width);
        await page.screenshot({path: `${out}/${name}-${width}.png`, fullPage:true});
      }
    }
    await page.locator('#tab-vision').click();
    await page.locator('#cx').fill('160');
    await page.locator('#cx').dispatchEvent('input');
    assert((await page.locator('#geometry').innerText()).includes('-0.5000'));
    await page.locator('#case').selectOption({index:3});
    assert((await page.locator('#case-output').innerText()).includes('stop'));
    await page.locator('#tab-weights').click();
    await page.locator('#train-step').click();
    assert((await page.locator('#training-output').innerText()).includes('0.220000'));
    await page.locator('#tab-fit').click();
    assert((await page.locator('#fit-rmse').innerText()).includes('14.34'));
    await page.locator('#fit-model').selectOption('legacy');
    assert((await page.locator('#fit-rmse').innerText()).includes('36.51'));
    await page.locator('#tab-replay').click();
    const initial = await page.locator('#chase').getAttribute('src');
    await page.locator('#timeline').fill('300');
    await page.locator('#timeline').dispatchEvent('input');
    assert.notEqual(await page.locator('#chase').getAttribute('src'), initial);
    await page.locator('#play').click();
    await page.waitForTimeout(200);
    assert(Number(await page.locator('#timeline').inputValue()) > 300);
    await page.locator('#play').click();
    assert(await page.locator('#chase').evaluate(i=>i.complete && i.naturalWidth>0));
    const canvasNonblank = await page.locator('#path-canvas').evaluate(c => {
      const a = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
      let opaque=0; for(let i=3;i<a.length;i+=4) if(a[i]) opaque++;
      return opaque>1000;
    });
    assert(canvasNonblank);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({offline:true,viewports:[1280,360],tabs:6,model_max_error:diff,geometry:true,training:true,validation:true,playback:true,canvas_nonblank:true,errors},null,2));
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
