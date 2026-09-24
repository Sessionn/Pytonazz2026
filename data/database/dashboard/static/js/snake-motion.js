/* Distance-sampled locomotion. The body follows travelled space, not pose lerps. */
(() => {
  const COUNT=61,CAPACITY=4096,STRIDE=.7;
  const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
  const ease=t=>{t=clamp(t,0,1);return t*t*t*(t*(t*6-15)+10);};
  const angle=x=>Math.atan2(Math.sin(x),Math.cos(x));
  const rest=new Float32Array(COUNT*3),raw=[];
  let length=0;
  for(let i=0;i<=600;i++) {
    const u=i/600,a=u*6.7-.8;
    const p=[185+Math.cos(a)*(145-55*u),85+Math.sin(a)*(43-12*u),Math.sin(a)*3];
    if(i)length+=Math.hypot(p[0]-raw[i-1].p[0],p[1]-raw[i-1].p[1]);
    raw.push({p,d:length});
  }
  let cursor=1;
  for(let i=0;i<COUNT;i++) {
    const distance=length*i/(COUNT-1);
    while(cursor<600&&raw[cursor].d<distance)cursor++;
    const a=raw[cursor-1],b=raw[cursor],t=(distance-a.d)/(b.d-a.d||1);
    for(let axis=0;axis<3;axis++)rest[i*3+axis]=a.p[axis]+(b.p[axis]-a.p[axis])*t;
  }
  function resting(out,cx=185,cy=85,scale=1) {
    for(let i=0;i<COUNT;i++) {
      out[i*3]=cx+(rest[i*3]-185)*scale;out[i*3+1]=cy+(rest[i*3+1]-85)*scale;out[i*3+2]=rest[i*3+2]*scale;
    }
    return out;
  }
  function uniforms(points,out,offsetX=0,offsetY=0) {
    for(let i=0;i<COUNT;i++) {
      out[(i+1)*4]=points[i*3]-offsetX;out[(i+1)*4+1]=points[i*3+1]-offsetY;out[(i+1)*4+2]=points[i*3+2];
    }
    for(let axis=0;axis<3;axis++) {
      out[axis]=2*out[4+axis]-out[8+axis];out[248+axis]=2*out[244+axis]-out[240+axis];out[252+axis]=2*out[248+axis]-out[244+axis];
    }
    return out;
  }
  class Trail {
    constructor(points) {
      this.points=new Float32Array(CAPACITY*3);this.latest=0;this.count=1;this.head=new Float64Array(3);this.seed(points);
    }
    seed(points) {
      this.count=1;this.latest=0;this.points.set(points.subarray(180,183),0);this.head.set(points.subarray(180,183));
      for(let i=59;i>=0;i--)this.push(points[i*3],points[i*3+1],points[i*3+2]);
    }
    push(x,y,z=0) {
      let last=this.latest*3;
      let distance=Math.hypot(x-this.points[last],y-this.points[last+1],z-this.points[last+2]);
      while(distance>=STRIDE) {
        const t=STRIDE/distance;
        const nx=this.points[last]+(x-this.points[last])*t,ny=this.points[last+1]+(y-this.points[last+1])*t,nz=this.points[last+2]+(z-this.points[last+2])*t;
        this.latest=(this.latest+1)%CAPACITY;last=this.latest*3;
        this.points[last]=nx;this.points[last+1]=ny;this.points[last+2]=nz;this.count=Math.min(CAPACITY,this.count+1);
        distance=Math.hypot(x-nx,y-ny,z-nz);
      }
      this.head[0]=x;this.head[1]=y;this.head[2]=z;
    }
    sample(out,bodyLength) {
      let index=this.latest,travelled=0,read=0;
      let ax=this.head[0],ay=this.head[1],az=this.head[2];
      let bx=this.points[index*3],by=this.points[index*3+1],bz=this.points[index*3+2];
      let segment=Math.hypot(bx-ax,by-ay,bz-az);
      for(let i=0;i<COUNT;i++) {
        const distance=bodyLength*i/(COUNT-1);
        while(travelled+segment<distance&&read<this.count-1) {
          travelled+=segment;ax=bx;ay=by;az=bz;index=(index-1+CAPACITY)%CAPACITY;read++;
          bx=this.points[index*3];by=this.points[index*3+1];bz=this.points[index*3+2];segment=Math.hypot(bx-ax,by-ay,bz-az);
        }
        const t=clamp((distance-travelled)/(segment||1),0,1);
        out[i*3]=ax+(bx-ax)*t;out[i*3+1]=ay+(by-ay)*t;out[i*3+2]=az+(bz-az)*t;
      }
    }
  }
  class Animal {
    constructor(points,scale=1) {
      this.points=points;this.trail=new Trail(points);this.scale=scale;
      this.heading=Math.atan2(points[1]-points[4],points[0]-points[3]);this.turn=0;this.speed=45*scale;this.time=0;
    }
    step(dt,goal,scale) {
      dt=clamp(dt,0,.04);this.time+=dt;this.scale+=(scale-this.scale)*(1-Math.exp(-dt*2));
      const head=this.trail.head,dx=goal.x-head[0],dy=goal.y-head[1];
      const distance=Math.hypot(dx,dy),target=Math.atan2(dy,dx);
      const responsive=goal.chase||goal.settle,turnLimit=responsive?5:1.8;
      const desiredTurn=clamp(angle(target-this.heading)*(responsive?5:2.6),-turnLimit,turnLimit);
      this.turn+=(desiredTurn-this.turn)*(1-Math.exp(-dt*(responsive?8:4)));this.heading+=this.turn*dt;
      const wanted=clamp(distance*(responsive?2.5:.8),goal.settle?0:19*this.scale,(goal.chase?360:goal.settle?240:125)*this.scale)*(goal.pace||1);
      this.speed+=(wanted-this.speed)*(1-Math.exp(-dt*(responsive?6:2.4)));
      const sway=Math.sin(this.time*2.4)*.16*Math.min(1,this.speed/(80*this.scale));
      const direction=this.heading+sway,z=head[2]+((goal.z||0)-head[2])*(1-Math.exp(-dt*2));
      this.trail.push(head[0]+Math.cos(direction)*this.speed*dt,head[1]+Math.sin(direction)*this.speed*dt,z);
      this.trail.sample(this.points,length*this.scale);
    }
  }
  // One closed track: resting body from tail to head, then a tangent bridge
  // back to the tail. Every body point follows the exact same travelled path.
  const loop=raw.slice().reverse().map(({p})=>({p,d:0}));
  // Continue around a broad inner coil rather than folding the neck through
  // the short gap between head and tail. A full sweep keeps curvature gentle.
  for(let i=1;i<=600;i++) {
    const t=i/600,a=-.8-(Math.PI*4-6.7)*t,blend=ease(t);
    loop.push({p:[185+Math.cos(a)*(145-55*blend),
      85+Math.sin(a)*(43-12*blend),Math.sin(a)*3+Math.sin(t*Math.PI)*5],d:0});
  }
  for(let i=1;i<loop.length;i++)loop[i].d=loop[i-1].d+Math.hypot(loop[i].p[0]-loop[i-1].p[0],loop[i].p[1]-loop[i-1].p[1]);
  const circuit=loop[loop.length-1].d;
  function refresh(out,t,cx=185,cy=85,scale=1) {
    const travelled=ease(t)*circuit;
    for(let i=0;i<COUNT;i++) {
      const distance=((length+travelled-length*i/(COUNT-1))%circuit+circuit)%circuit;
      let lo=0,hi=loop.length-1;
      while(hi-lo>1){const mid=(lo+hi)>>1;if(loop[mid].d<distance)lo=mid;else hi=mid;}
      const a=loop[lo],b=loop[hi],f=(distance-a.d)/(b.d-a.d||1);
      out[i*3]=cx+(a.p[0]+(b.p[0]-a.p[0])*f-185)*scale;
      out[i*3+1]=cy+(a.p[1]+(b.p[1]-a.p[1])*f-85)*scale;
      out[i*3+2]=(a.p[2]+(b.p[2]-a.p[2])*f)*scale;
    }
  }
  function gesture(points,time,kind,energy,scale=1) {
    for(let i=0;i<COUNT;i++) {
      const u=i/(COUNT-1),head=Math.exp(-u*8),tail=Math.pow(u,5);
      const wave=Math.sin(time*7-u*5)*energy*scale;
      if(kind==='nod')points[i*3+2]+=wave*7*head;
      else if(kind==='look')points[i*3]+=wave*5*head;
      else if(kind==='ripple')points[i*3+2]+=wave*4*Math.sin(u*Math.PI);
      else {points[i*3+2]+=energy*scale*(tail*12-head*2);points[i*3+1]+=wave*5*tail;}
    }
  }
  globalThis.PythonMotion={COUNT,length,rest,resting,uniforms,Trail,Animal,refresh,gesture,ease};
})();
