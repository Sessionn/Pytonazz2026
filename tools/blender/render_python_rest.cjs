// Render the exact resting motion curve to a transparent 2x PNG.
// Run against the disposable preview, never the production dashboard.
const {chromium}=require('playwright');
const fs=require('node:fs');
(async()=>{
  const base=process.env.DASHBOARD_TEST_URL||'http://127.0.0.1:5056';
  if(!['127.0.0.1','localhost'].includes(new URL(base).hostname))throw new Error('Local preview required');
  const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE});
  try {
    const page=await browser.newPage({reducedMotion:'reduce'});await page.goto(base+'/login');
    const data=await page.evaluate(async()=>{
      const canvas=document.createElement('canvas');
      const renderer=await PythonMesh.create(canvas);
      if(!renderer)throw new Error('WebGL required to render the poster');
      const points=PythonMotion.resting(new Float32Array(183));
      renderer.draw(PythonMotion.uniforms(points,new Float32Array(256)),1,370,170,2);
      const png=canvas.toDataURL('image/png');renderer.dispose();return png.split(',')[1];
    });
    fs.writeFileSync('data/database/dashboard/static/models/python/rest.png',Buffer.from(data,'base64'));
    console.log('OK: 740×340 PNG rendered from the same curve, mesh and shader');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
