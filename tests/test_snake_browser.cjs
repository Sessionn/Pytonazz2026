// Local disposable preview only. Test visible state, idle GPU and explicit refresh.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const base=process.env.DASHBOARD_TEST_URL||'http://127.0.0.1:5056';
assert(['localhost','127.0.0.1'].includes(new URL(base).hostname));
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE});
 try {
  const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'no-preference'});
  await context.addInitScript(()=>{
   window.draws=0;window.uploads=0;
   const draw=WebGLRenderingContext.prototype.drawElements,upload=WebGLRenderingContext.prototype.bufferData;
   WebGLRenderingContext.prototype.drawElements=function(...a){window.draws++;return draw.apply(this,a);};
   WebGLRenderingContext.prototype.bufferData=function(...a){window.uploads++;return upload.apply(this,a);};
  });
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/login');await page.waitForFunction(()=>window.draws>2);
  const first=await page.locator('.python-overlay').screenshot();await page.waitForTimeout(250);
  assert(!first.equals(await page.locator('.python-overlay').screenshot()),'Autonomous movement with no input');
  const uploads=await page.evaluate(()=>window.uploads);await page.mouse.move(600,620);await page.waitForTimeout(250);
  assert.equal(await page.evaluate(()=>window.uploads),uploads,'No per-frame mesh uploads');
  await page.getByLabel('Utente',{exact:true}).focus();
  for(const kind of ['nod','look','ripple']) {
   await page.locator('#username').pressSequentially('a');
   await page.waitForFunction(k=>document.querySelector('canvas').dataset.gesture===k,kind);
   await page.waitForFunction(()=>document.querySelector('canvas').dataset.gesture==='none');
  }
  await page.getByLabel('Utente',{exact:true}).fill('preview');
  await page.waitForFunction(()=>document.querySelector('canvas').dataset.pose==='username');
  await page.waitForFunction(()=>document.querySelector('canvas').dataset.settled==='true');
  await page.mouse.move(10,10);
  await page.waitForTimeout(150);
  assert.equal(await page.locator('canvas').getAttribute('data-pose'),'username','Focused input owns the pose, even after mouse movement');
  await page.getByLabel('Password',{exact:true}).fill('wrong');
  await page.waitForFunction(()=>document.querySelector('canvas').dataset.pose==='password');
  await page.waitForFunction(()=>document.querySelector('canvas').dataset.settled==='true');
  await page.mouse.move(1300,40);
  assert.equal(await page.locator('canvas').getAttribute('data-pose'),'password');
  await page.locator('#password').pressSequentially('a');
  await page.waitForFunction(()=>document.querySelector('canvas').dataset.gesture==='guard');
  await page.locator('[type=submit]').click();await page.locator('.login-error').waitFor();
  await page.getByLabel('Password',{exact:true}).fill('preview-only');
  await page.evaluate(()=>window.originalCanvas=document.querySelector('.python-overlay'));
  await page.locator('[type=submit]').click();await page.locator('.song-details').first().waitFor();
  await page.waitForFunction(()=>document.querySelector('.snake-stage').dataset.motion==='arrival');
  assert(await page.evaluate(()=>document.querySelector('.python-overlay')===window.originalCanvas));
  await page.waitForFunction(()=>document.querySelector('.snake-stage').dataset.motion==='rest');
  assert(await page.locator('.snake-poster').isVisible());
  assert((await page.locator('.snake-poster').getAttribute('src')).endsWith('/rest.png'));
  assert.equal(await page.locator('canvas').count(),0,'Rest is a real PNG, no visible/offscreen canvas node');
  const drawCount=await page.evaluate(()=>window.draws);
  const before=await page.locator('.snake-poster').boundingBox();await page.evaluate(()=>scrollTo(0,120));
  const after=await page.locator('.snake-poster').boundingBox();
  assert(Math.abs(before.y-after.y-120)<2,'PNG must move with page scrolling');
  await page.mouse.move(1200,400);await page.evaluate(()=>refreshStats());
  await page.getByRole('link',{name:'Catalogo tracce',exact:true}).click();await page.waitForTimeout(350);
  assert.equal(await page.evaluate(()=>window.draws),drawCount,'Scroll, pointer, stats and section navigation must not render');
  await page.locator('[data-python-refresh]').last().click();
  await page.waitForFunction(()=>document.querySelector('.snake-stage').dataset.motion==='refresh');
  assert(await page.locator('.python-local').isVisible());
  assert.equal(await page.locator('.snake-poster').isVisible(),false);
  const during=await page.locator('.python-local').boundingBox();await page.evaluate(()=>scrollBy(0,50));
  const scrolled=await page.locator('.python-local').boundingBox();
  assert(Math.abs(during.y-scrolled.y-50)<2,'Refresh canvas must also belong to the page');
  await page.locator('[data-python-refresh]').last().click();
  await page.waitForFunction(()=>document.querySelector('.snake-stage').dataset.motion==='rest');
  const stopped=await page.evaluate(()=>window.draws);await page.waitForTimeout(250);
  assert.equal(await page.evaluate(()=>window.draws),stopped,'Finite refresh must stop drawing');
  // Direct authenticated navigation must not even fetch the animated model.
  const direct=await context.newPage();let assets=0;
  direct.on('request',r=>{if(/python\.mesh|skin\.webp|normal\.webp/.test(r.url()))assets++;});
  await direct.goto(base+'/');await direct.locator('.song-details').first().waitFor();
  assert.equal(assets,0);assert.equal(await direct.evaluate(()=>window.draws),0);
  await direct.setViewportSize({width:390,height:844});
  assert(await direct.locator('.snake-poster').isVisible());
  await direct.locator('[data-python-refresh]').last().click();
  await direct.waitForFunction(()=>document.querySelector('.snake-stage').dataset.motion==='refresh');
  await direct.evaluate(()=>{
    Object.defineProperty(document,'hidden',{configurable:true,value:true});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  assert.equal(await direct.locator('.snake-stage').getAttribute('data-motion'),'rest');
  await direct.evaluate(()=>{
    Object.defineProperty(document,'hidden',{configurable:true,value:false});
    document.dispatchEvent(new Event('visibilitychange'));
  });
  const mobileDraws=await direct.evaluate(()=>window.draws);
  await direct.waitForTimeout(200);
  assert.equal(await direct.evaluate(()=>window.draws),mobileDraws,'Hidden-tab cancellation cannot replay on return');
  await direct.emulateMedia({reducedMotion:'reduce'});
  await direct.locator('[data-python-refresh]').last().click();await direct.waitForTimeout(250);
  assert.equal(await direct.evaluate(()=>window.draws),mobileDraws,'Reduced motion keeps PNG');
  const fallback=await browser.newPage();
  await fallback.addInitScript(()=>{HTMLCanvasElement.prototype.getContext=()=>null;});
  await fallback.goto(base+'/login');await fallback.waitForFunction(()=>document.querySelector('.snake-stage').dataset.motion==='fallback');
  assert(await fallback.locator('.snake-poster').isVisible());
  await fallback.locator('#username').fill('preview');await fallback.locator('#password').fill('preview-only');
  await fallback.locator('[type=submit]').click();await fallback.locator('.song-details').first().waitFor();
  assert(await fallback.locator('.snake-poster').isVisible());assert.deepEqual(errors,[]);
  console.log('OK: autonomous login, continuous canvas arrival, real PNG rest, zero idle draws/assets, document scroll, finite crawling refresh, varied typing reactions, reduced motion, fallback');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
