/* One persistent renderer. Pose updates touch only 64 control points, not vertices. */
(async () => {
  let stage = document.querySelector('.snake-stage');
  if (!stage) return;
  const canvas = stage.querySelector('canvas');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const spine = new Float32Array(64 * 4);
  const target = new Float32Array(61 * 3);
  let renderer;
  try { renderer = await window.PythonMesh.create(canvas); } catch (_) { renderer = null; }
  let toggle, observer, visibilityObserver, homeVisible = true;
  let frame = 0, last = 0, phase = 0, paused = reduced.matches;
  let mode = document.body.classList.contains('login-page') ? 'idle' : 'dashboard';
  let width = innerWidth, height = innerHeight, size = 1, desiredSize = 1, home, field, dirty = true;
  let pointerX = width * .3, pointerY = height * .55, initialized = false;
  let travelStart = 0, travelFrom = null;
  try { phase = Number(sessionStorage.getItem('snake-phase')) || 0; paused ||= sessionStorage.getItem('snake-paused') === '1'; } catch (_) {}

  function fallback() {
    canvas.hidden = true;
    if (!stage.querySelector('.snake-fallback')) {
      const el = document.createElement('div'); el.className = 'snake-fallback'; el.textContent = '〰';
      el.setAttribute('aria-hidden', 'true'); stage.append(el);
    }
    if (toggle) toggle.hidden = true;
  }
  function label() {
    toggle.textContent = paused ? '▶' : 'Ⅱ';
    toggle.setAttribute('aria-label', paused ? 'Riprendi animazione' : 'Pausa animazione');
    toggle.setAttribute('aria-pressed', String(paused));
  }
  function attach() {
    stage = document.querySelector('.snake-stage');
    if (!stage) return;
    // The original canvas survives the authenticated page change.
    stage.querySelector('canvas')?.remove();
    canvas.className = 'python-overlay';
    canvas.setAttribute('aria-hidden','true');
    document.body.append(canvas);
    toggle = stage.querySelector('button');
    toggle.addEventListener('click', () => {
      paused = !paused; label();
      try { sessionStorage.setItem('snake-paused', paused ? '1' : '0'); } catch (_) {}
      wake();
    });
    observer?.disconnect();
    observer = new ResizeObserver(() => { dirty = true; wake(); });
    observer.observe(stage);
    visibilityObserver?.disconnect();
    visibilityObserver = new IntersectionObserver(entries=>{
      homeVisible=entries[0].isIntersecting;
      last=0;wake();
    });
    visibilityObserver.observe(stage);
    document.querySelectorAll('.login-card,input').forEach(el => observer.observe(el));
    label(); dirty = true;
    if (!renderer) fallback();
  }
  function measure() {
    width = innerWidth; height = innerHeight;
    home = stage.getBoundingClientRect();
    const input = document.getElementById(mode === 'password' ? 'password' : 'username');
    field = input?.getBoundingClientRect();
    desiredSize = mode === 'dashboard' ? Math.min(1,home.width / 370,home.height / 155)
      : mode === 'idle' ? Math.min(1.65,home.width / 330) : Math.min(1.15,width / 700);
    // Large enough to show individual scales, including on mobile.
    desiredSize = Math.max(.48,desiredSize);
    dirty = false;
  }
  function setPoint(i,x,y,z=0) { const k=i*3;target[k]=x;target[k+1]=y;target[k+2]=z; }
  function homePose() {
    const cx=home.left+home.width*.5, cy=home.top+home.height*.5;
    for(let i=0;i<=60;i++) {
      const u=i/60, a=u*6.7-.8;
      setPoint(i,cx+Math.cos(a)*(145-55*u)*size,cy+Math.sin(a)*(43-12*u)*size+Math.sin(phase*.8-u*5)*2*size,Math.sin(a)*3);
    }
  }
  function fieldPose() {
    if(!field) { homePose(); return; }
    const cx=field.left+field.width/2, cy=field.top+field.height/2;
    const rx=field.width/2+22*size, ry=field.height/2+12*size;
    for(let i=0;i<=60;i++) {
      const u=i/60, a=-.65-u*5.9+Math.sin(phase*.5)*.035;
      // Rounded rectangular crawl around the outside of the input.
      const c=Math.cos(a),s=Math.sin(a);
      setPoint(i,cx+Math.sign(c)*Math.pow(Math.abs(c),.75)*rx,
        cy+Math.sign(s)*Math.pow(Math.abs(s),.75)*ry,2+Math.sin(u*8+phase)*1.5);
    }
    if(mode==='password') {
      // Rest in a compact, layered coil on the right rim, clear of the label.
      // The smaller silhouette fits the gap between inputs even on a phone.
      const coilX=field.right-65*size,coilY=field.top-22*size;
      for(let i=0;i<=60;i++){
        const u=i/60,a=-.65-u*10.8,r=(1-u*.66);
        setPoint(i,coilX+Math.cos(a)*59*r*size,coilY+Math.sin(a)*16*r*size,
          5+u*12*size);
      }
      // The final tail arc rises over the nose and both eyes. The field stays clear.
      const hx=target[0],hy=target[1];
      const dx=target[0]-target[3],dy=target[1]-target[4],length=Math.hypot(dx,dy)||1;
      const fx=dx/length,fy=dy/length,sx=-fy,sy=fx;
      const startX=target[38*3],startY=target[38*3+1];
      for(let i=39;i<=60;i++) {
        const k=i*3;
        if(i<49){
          const u=(i-38)/11;
          const endX=hx+fx*16*size+sx*16*size,endY=hy+fy*16*size+sy*16*size;
          const controlX=hx-fx*60*size+sx*50*size,controlY=hy-fy*60*size+sy*50*size;
          target[k]=(1-u)*(1-u)*startX+2*(1-u)*u*controlX+u*u*endX;
          target[k+1]=(1-u)*(1-u)*startY+2*(1-u)*u*controlY+u*u*endY;
          target[k+2]=u*20*size;
        }else{
          const u=(i-49)/11,across=16-u*39;
          target[k]=hx+fx*(16+Math.sin(u*Math.PI)*2)*size+sx*across*size;
          target[k+1]=hy+fy*(16+Math.sin(u*Math.PI)*2)*size+sy*across*size;
          target[k+2]=20*size;
        }
      }
    }
  }
  function followPose(dt) {
    // Head seeks the actual pointer; each vertebra follows the previous one.
    // Bounded velocity avoids teleporting on large pointer jumps.
    const headX=spine[4],headY=spine[5];
    const aimX=pointerX-spine[8],aimY=pointerY-spine[9],aimLength=Math.hypot(aimX,aimY)||1;
    const dx=pointerX-aimX/aimLength*30*size-headX;
    const dy=pointerY-aimY/aimLength*30*size-headY,dist=Math.hypot(dx,dy);
    const step=Math.min(dist,dt*(200+dist*3));
    const directionX=dx/(dist||1),directionY=dy/(dist||1);
    setPoint(0,headX+directionX*step,headY+directionY*step);
    const gap=8.2*size;
    for(let i=1;i<=60;i++) {
      const k=i*3,p=(i+1)*4;
      let vx=spine[p]-target[k-3],vy=spine[p+1]-target[k-2];
      const length=Math.hypot(vx,vy)||1;
      const wave=Math.sin(phase*3-i*.25)*Math.min(1,dist/80)*.85*size;
      setPoint(i,target[k-3]+vx/length*gap-vy/length*wave,target[k-2]+vy/length*gap+vx/length*wave,0);
    }
  }
  function draw(now) {
    frame=0;
    if(document.hidden || !renderer) return;
    if(mode==='dashboard'&&!homeVisible&&!travelFrom){renderer.clear();return;}
    if(dirty) measure();
    const dt=last ? Math.min((now-last)/1000,.04) : 1/60;
    last=now;
    size+=(desiredSize-size)*(!initialized||paused?1:1-Math.exp(-dt*5));
    if(!paused) phase+=dt;
    if(mode==='username'||mode==='password') fieldPose();
    else if(mode==='follow' && initialized) followPose(paused?0:dt);
    else homePose();
    // Smoothstep travel leaves the exact login pose intact at t=0.
    const travel=travelFrom ? Math.min(1,(now-travelStart)/1250) : 1;
    const blend=travel*travel*(3-2*travel);
    const follow = mode==='follow';
    const alpha=!initialized || paused ? 1 : follow ? 1 : 1-Math.exp(-dt*6);
    for(let i=0;i<=60;i++) for(let axis=0;axis<3;axis++) {
      const k=(i+1)*4+axis;
      let value=target[i*3+axis];
      if(travelFrom) value=travelFrom[k]+(value-travelFrom[k])*blend;
      spine[k]+=(value-spine[k])*(travelFrom?1:alpha);
    }
    for(let axis=0;axis<3;axis++) {
      spine[axis]=2*spine[4+axis]-spine[8+axis];
      spine[248+axis]=2*spine[244+axis]-spine[240+axis];
      spine[252+axis]=2*spine[248+axis]-spine[244+axis];
    }
    initialized=true;
    renderer.draw(spine,size,width,height,Math.min(devicePixelRatio||1,2));
    canvas.dataset.pose=mode;
    if(travel>=1) travelFrom=null;
    if(!paused || travelFrom) frame=requestAnimationFrame(draw);
  }
  function wake() { if(!frame && !document.hidden && renderer) frame=requestAnimationFrame(draw); }
  function remember() { try { sessionStorage.setItem('snake-phase',String(phase)); } catch (_) {} }
  function focusedPose() {
    const el=document.activeElement;
    if(el?.closest('.pwd-wrap')) return 'password';
    return el?.id==='username' ? 'username' : null;
  }

  document.addEventListener('pointermove',e=>{
    if(!document.body.classList.contains('login-page') || e.pointerType==='touch') return;
    pointerX=e.clientX;pointerY=e.clientY;
    if(!focusedPose() && mode!=='follow') {mode='follow';dirty=true;}
    wake();
  },{passive:true});
  document.addEventListener('focusin',e=>{
    if(!document.body.classList.contains('login-page')) return;
    const focus=focusedPose();
    if(focus) {mode=focus;dirty=true;wake();}
  });
  document.addEventListener('focusout',()=>{
    if(!document.body.classList.contains('login-page')) return;
    queueMicrotask(()=>{
      if(!focusedPose()) {mode='follow';dirty=true;wake();}
    });
  });
  document.addEventListener('visibilitychange',()=>{last=0;if(document.hidden){cancelAnimationFrame(frame);frame=0;}else wake();});
  addEventListener('resize',()=>{dirty=true;wake();},{passive:true});
  addEventListener('scroll',()=>{dirty=true;wake();},{passive:true,capture:true});
  reduced.addEventListener('change',()=>{paused=reduced.matches;label();wake();});
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();cancelAnimationFrame(frame);frame=0;renderer=null;fallback();});
  addEventListener('pagehide',()=>{remember();cancelAnimationFrame(frame);frame=0;});
  addEventListener('pageshow',wake);
  document.addEventListener('pytonazz:dashboard',()=>{
    remember();travelFrom=paused?null:spine.slice();travelStart=performance.now();mode='dashboard';
    attach();wake();
  });
  attach();
  if(['username','password'].includes(document.activeElement?.id)) mode=document.activeElement.id;
  wake();
})();
