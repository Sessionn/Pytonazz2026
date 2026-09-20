// Run only against the disposable tools/preview_dashboard.py server.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = process.env.DASHBOARD_TEST_URL || 'http://127.0.0.1:5055';
assert(['127.0.0.1','localhost'].includes(new URL(base).hostname));
(async () => {
  const browser = await chromium.launch({ headless:true, executablePath:process.env.BROWSER_EXECUTABLE });
  try {
    const page = await browser.newPage({ reducedMotion:'no-preference',viewport:{width:1440,height:1000} });
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>{
      window.uploads=0;window.draws=0;
      const upload=WebGLRenderingContext.prototype.bufferData;
      WebGLRenderingContext.prototype.bufferData=function(...args){window.uploads++;return upload.apply(this,args);};
      const draw=WebGLRenderingContext.prototype.drawElements;
      WebGLRenderingContext.prototype.drawElements=function(...args){window.draws++;return draw.apply(this,args);};
    });
    await page.goto(base+'/login');
    const canvas=page.locator('canvas.python-overlay');
    await page.waitForFunction(()=>window.draws>2);
    assert.equal(await page.locator('.snake-fallback').count(),0,'Shaders must compile, not silently fall back');
    await page.evaluate(()=>window.originalCanvas=document.querySelector('canvas'));
    const before=await canvas.screenshot();
    await page.mouse.move(600,700);
    await page.waitForTimeout(450);
    assert.equal(await canvas.getAttribute('data-pose'),'follow');
    assert(!before.equals(await canvas.screenshot()),'Snake must move');
    assert.equal(await page.locator('.snake-stage').innerText(),'Ⅱ');
    const uploads=await page.evaluate(()=>window.uploads);
    await page.waitForTimeout(400);
    assert.equal(await page.evaluate(()=>window.uploads),uploads,'Mesh must never rebuild each frame');
    await page.getByLabel('Utente',{exact:true}).fill('preview');
    await page.waitForFunction(()=>document.querySelector('canvas').dataset.pose==='username');
    await page.getByLabel('Password',{exact:true}).fill('wrong-password');
    await page.waitForFunction(()=>document.querySelector('canvas').dataset.pose==='password');
    await page.getByRole('button',{name:'Mostra/nascondi password'}).click();
    await page.mouse.move(500,500);
    assert.equal(await canvas.getAttribute('data-pose'),'password','Password toggle keeps the protective pose');
    await page.getByRole('button',{name:'Accedi',exact:true}).click();
    await page.locator('.login-error').waitFor();
    assert(await page.evaluate(()=>document.querySelector('canvas')===window.originalCanvas));
    assert.equal(new URL(page.url()).pathname,'/login');
    await page.getByLabel('Password',{exact:true}).fill('preview-only');
    await page.getByRole('button',{name:'Accedi',exact:true}).click();
    await page.locator('.song-details').first().waitFor();
    assert.equal(new URL(page.url()).pathname,'/');
    assert(await page.evaluate(()=>document.querySelector('canvas')===window.originalCanvas),'Same live WebGL context survives login');
    assert(await page.evaluate(()=>Number(sessionStorage.getItem('snake-phase'))>0));
    await page.mouse.move(200,100);
    await page.waitForTimeout(200);
    assert.equal(await canvas.getAttribute('data-pose'),'dashboard','Mouse tracking is login-only');
    await page.waitForTimeout(1400);
    // Unchanged refresh must preserve focused nodes, thumbnails, and row identity.
    await page.locator('.song-details').first().focus();
    await page.evaluate(()=>{window.firstRow=document.querySelector('#songs-body tr');window.focused=document.activeElement;fetchSongs(false);});
    await page.waitForFunction(()=>!document.querySelector('#songs-body').hasAttribute('aria-busy'));
    assert(await page.evaluate(()=>window.firstRow===document.querySelector('#songs-body tr')));
    assert(await page.evaluate(()=>window.focused===document.activeElement));
    await page.getByRole('button',{name:'Pausa animazione',exact:true}).click();
    await page.waitForTimeout(100);
    const draws=await page.evaluate(()=>window.draws);
    await page.waitForTimeout(180);
    assert.equal(await page.evaluate(()=>window.draws),draws,'Paused scene must not run a render loop');
    assert.deepEqual(errors,[]);
    fs.mkdirSync('data/tmp/web-review',{recursive:true});
    await page.screenshot({path:'data/tmp/web-review/python-dashboard-verified.png'});

    const fallback=await browser.newPage();
    await fallback.addInitScript(()=>{
      const original=HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext=function(kind,...args){return kind==='webgl'?null:original.call(this,kind,...args);};
    });
    await fallback.goto(base+'/login');
    assert.equal(await fallback.locator('.snake-fallback').count(),1);
    await fallback.getByLabel('Utente',{exact:true}).fill('preview');
    await fallback.getByLabel('Password',{exact:true}).fill('preview-only');
    await fallback.getByRole('button',{name:'Accedi',exact:true}).click();
    await fallback.locator('.song-details').first().waitFor();
    assert.equal(await fallback.locator('.snake-fallback').count(),1);
    const native=await browser.newPage({javaScriptEnabled:false,reducedMotion:'reduce'});
    await native.goto(base+'/login');
    await native.getByLabel('Utente',{exact:true}).fill('preview');
    await native.getByLabel('Password',{exact:true}).fill('preview-only');
    await native.getByLabel('Password',{exact:true}).press('Enter');
    await native.waitForURL(base+'/');
    console.log('OK: stable GPU buffers, login-only follow, field poses, failed login, persistent canvas transition, stable rows/focus, pause, no-WebGL and native POST');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
