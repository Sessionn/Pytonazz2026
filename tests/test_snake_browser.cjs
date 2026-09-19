// Run only against tools/preview_dashboard.py and its disposable database.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ headless:true, executablePath:process.env.BROWSER_EXECUTABLE });
  try {
    const page = await browser.newPage({ reducedMotion:'no-preference' });
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:5055/login');
    const canvas=page.locator('.snake-stage canvas');
    const before=await canvas.screenshot();
    await page.waitForTimeout(250);
    assert(!before.equals(await canvas.screenshot()),'Snake must animate');
    assert.equal(await page.locator('.snake-stage').innerText(),'Ⅱ');
    await page.getByLabel('Utente',{exact:true}).fill('preview');
    await page.getByLabel('Password',{exact:true}).fill('preview-only');
    await page.getByRole('button',{name:'Accedi',exact:true}).click();
    await page.locator('.song-details').first().waitFor();
    assert(await page.evaluate(()=>Number(sessionStorage.getItem('snake-phase'))>0));
    await page.getByRole('button',{name:'Pausa animazione',exact:true}).click();
    assert.equal(await page.locator('.snake-toggle').innerText(),'▶');
    assert.deepEqual(errors,[]);
    const fallback=await browser.newPage();
    await fallback.addInitScript(()=>{
      const original=HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext=function(kind,...args){return kind==='webgl'?null:original.call(this,kind,...args);};
    });
    await fallback.goto('http://127.0.0.1:5055/login');
    assert.equal(await fallback.locator('.snake-fallback').count(),1);
    assert(await fallback.getByRole('button',{name:'Accedi',exact:true}).isVisible());
    console.log('OK: animated mesh, continuity, icon-only pause, no-WebGL login fallback');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
