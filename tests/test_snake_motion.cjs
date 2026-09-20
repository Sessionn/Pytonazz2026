const assert=require('node:assert/strict');
require('../data/database/dashboard/static/js/snake-motion.js');
const M=globalThis.PythonMotion;
const out=new Float32Array(183),baseline=M.resting(new Float32Array(183));
for(const t of [0,1]) {M.refresh(out,t);out.forEach((v,i)=>assert(Math.abs(v-baseline[i])<.0001));}
M.refresh(out,.5);
for(let i=0;i<61;i++)assert(Math.abs(Math.hypot(out[i*3]-185,out[i*3+1]-85)-54)<.001,'Refresh forms a circle');
function simulate(fps){const p=M.resting(new Float32Array(183)),animal=new M.Animal(p);let travelled=0;
 for(let i=0;i<fps*8;i++){
  const x=p[0],y=p[1];animal.step(1/fps,{x:i<fps*4?400:50,y:140,z:2},1);
  const step=Math.hypot(p[0]-x,p[1]-y);assert(step<130/fps);travelled+=step;
  assert([...p].every(Number.isFinite));
  for(let j=1;j<61;j++)assert(Math.hypot(p[j*3]-p[(j-1)*3],p[j*3+1]-p[(j-1)*3+1])<M.length/60+.2,'Body cannot stretch');
 }
 assert(travelled>100,'No static login pose');return p;
}
const a=simulate(60),b=simulate(120);
assert(Math.hypot(a[0]-b[0],a[1]-b[1])<8,'Motion is approximately frame-rate independent');
console.log('OK: finite O endpoints, continuous bounded speed, body length, frame-rate independence');
