const assert=require('node:assert/strict');
require('../data/database/dashboard/static/js/snake-motion.js');
const M=globalThis.PythonMotion;
const out=new Float32Array(183),baseline=M.resting(new Float32Array(183));
for(const kind of ['username','password']) {
 const target=new Float32Array(183);
 M.fieldPose(target,{x:920,y:580,w:370,h:50},kind,1);
 M.transition(out,baseline,target,0);assert.deepEqual(out,baseline);
 M.transition(out,baseline,target,1);assert.deepEqual(out,target);
 for(let i=1;i<60;i++){M.transition(out,baseline,target,i/60);assert([...out].every(Number.isFinite));}
}
for(const t of [0,1]) {M.refresh(out,t);out.forEach((v,i)=>assert(Math.abs(v-baseline[i])<.0001));}
let changedShape=false;
for(let frame=1;frame<=252;frame++) {
 const previous=out.slice();M.refresh(out,frame/252);
 assert([...out].every(Number.isFinite));
 for(let i=1;i<61;i++)assert(Math.hypot(out[i*3]-out[(i-1)*3],out[i*3+1]-out[(i-1)*3+1])<=M.length/60+.05,'Crawling preserves body spacing');
 if(frame>1)assert(Math.hypot(out[0]-previous[0],out[1]-previous[1])<10,'No head teleport between frames');
 if(Math.abs(Math.hypot(out[0]-out[90],out[1]-out[91])-Math.hypot(baseline[0]-baseline[90],baseline[1]-baseline[91]))>5)changedShape=true;
}
assert(changedShape,'Body bends along the track instead of rotating as a rigid image');
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
console.log('OK: continuous crawling and exact return, distinct gestures, fast pursuit, docking, bounded speed, body length, frame-rate independence');
