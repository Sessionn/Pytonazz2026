const assert=require('node:assert/strict');
require('../data/database/dashboard/static/js/snake-motion.js');
const M=globalThis.PythonMotion;
const out=new Float32Array(183),baseline=M.resting(new Float32Array(183));
for(const t of [0,1]) {M.refresh(out,t);out.forEach((v,i)=>assert(Math.abs(v-baseline[i])<.0001));}
for(const t of [.1,.25,.5,.75]) {
 M.refresh(out,t);
 for(let i=0;i<61;i++)assert(Math.abs(Math.hypot(out[i*3]-185,out[i*3+1]-85)-Math.hypot(baseline[i*3]-185,baseline[i*3+1]-85))<.001,'Rotation preserves silhouette radius');
}
M.refresh(out,.1);
assert((baseline[0]-185)*(out[1]-85)-(baseline[1]-85)*(out[0]-185)>0,'Clockwise in screen coordinates');
const gestures=['nod','look','ripple','guard'].map(kind=>{const p=baseline.slice();M.gesture(p,.2,kind,1);assert([...p].every(Number.isFinite));return Array.from(p);});
for(let i=0;i<gestures.length;i++)for(let j=i+1;j<gestures.length;j++)assert.notDeepEqual(gestures[i],gestures[j]);
function approach(mode,seconds){const p=baseline.slice(),animal=new M.Animal(p);for(let i=0;i<seconds*60;i++)animal.step(1/60,{x:600,y:100,z:2,...mode},1);return Math.hypot(p[0]-600,p[1]-100);}
assert(approach({chase:true},1)<approach({},1),'Mouse pursuit responds faster than autonomous motion');
assert(approach({settle:true},8)<5,'Docking brakes near the field');
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
console.log('OK: clockwise shape-preserving rotation, distinct gestures, fast pursuit, docking, bounded speed, body length, frame-rate independence');
