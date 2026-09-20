/* Login locomotion -> finite arrival -> PNG. Only an explicit refresh animates
 * the dashboard. Scrolling and table/navigation updates never wake its GPU. */
(() => {
  const motion=window.PythonMotion;
  let stage=document.querySelector('.snake-stage');
  if(!stage||!motion)return;
  const canvas=stage.querySelector('canvas')||document.createElement('canvas');
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const points=new Float32Array(183),spine=new Float32Array(256),destination=new Float32Array(183);
  let state=document.body.classList.contains('login-page')?'login':'rest';
  let renderer=null,loading=null,animal=null,frame=0,last=0,elapsed=0,scale=1,contextReady=true;
  let poster,toggle,resizeObserver,home,field,dirty=true,paused=reduced.matches;
  let pointer=null,focus=null,phase=0,arrival=null,refreshPending=false;
  let viewportWidth=innerWidth,viewportHeight=innerHeight;
  try{paused ||= sessionStorage.getItem('snake-paused')==='1';phase=Number(sessionStorage.getItem('snake-phase'))||0;}catch(_){}
  canvas.setAttribute('aria-hidden','true');

  function bindStage() {
    stage=document.querySelector('.snake-stage');if(!stage)return;
    stage.querySelector('canvas')?.remove();
    poster=stage.querySelector('.snake-poster');toggle=stage.querySelector('.snake-toggle');
    if(toggle) {
      toggle.hidden=state!=='login';toggle.textContent=paused?'▶':'Ⅱ';
      toggle.setAttribute('aria-label',paused?'Riprendi animazione':'Pausa animazione');toggle.setAttribute('aria-pressed',String(paused));
      toggle.onclick=()=>{
        paused=!paused;try{sessionStorage.setItem('snake-paused',paused?'1':'0');}catch(_){}
        toggle.textContent=paused?'▶':'Ⅱ';toggle.setAttribute('aria-pressed',String(paused));
        toggle.setAttribute('aria-label',paused?'Riprendi animazione':'Pausa animazione');last=0;
        if(paused){cancelAnimationFrame(frame);frame=0;}else startLogin();
      };
    }
    resizeObserver?.disconnect();
    resizeObserver=new ResizeObserver(()=>{dirty=true;if(state!=='rest')wake();});resizeObserver.observe(stage);
    document.querySelectorAll('.login-card,input').forEach(el=>resizeObserver.observe(el));dirty=true;
  }
  function measure() {
    const rect=stage.getBoundingClientRect();home={x:rect.left+scrollX,y:rect.top+scrollY,w:rect.width,h:rect.height};
    const input=document.getElementById(focus==='password'?'password':'username'),f=input?.getBoundingClientRect();
    field=f?{x:f.left+scrollX,y:f.top+scrollY,w:f.width,h:f.height}:null;
    viewportWidth=innerWidth;viewportHeight=innerHeight;dirty=false;
  }
  const homeScale=()=>Math.max(.2,Math.min(home.w/370,home.h/170));
  function mountOverlay() {
    canvas.className='python-overlay';canvas.hidden=false;document.body.append(canvas);if(poster)poster.hidden=true;
  }
  function staticRest() {
    state='rest';elapsed=0;last=0;arrival=null;cancelAnimationFrame(frame);frame=0;canvas.hidden=true;canvas.remove();
    if(poster)poster.hidden=false;if(toggle)toggle.hidden=true;stage.dataset.motion='rest';
  }
  function fallback() {
    cancelAnimationFrame(frame);frame=0;canvas.hidden=true;canvas.remove();
    if(poster)poster.hidden=false;if(toggle)toggle.hidden=true;stage.dataset.motion='fallback';if(state!=='login')state='rest';
  }
  async function ensureRenderer() {
    if(!contextReady)return null;
    if(renderer)return renderer;
    if(!loading)loading=window.PythonMesh.create(canvas).then(value=>renderer=value).catch(()=>null);
    return loading;
  }
  async function startLogin() {
    if(state!=='login'||paused)return;
    if(!await ensureRenderer()){fallback();return;}if(state!=='login')return;
    measure();scale=Math.max(.55,Math.min(1.2,home.w/370));
    if(!animal){motion.resting(points,home.x+home.w/2,home.y+home.h/2,scale);animal=new motion.Animal(points,scale);}
    mountOverlay();wake();
  }
  function loginGoal(now) {
    if(focus&&field) {
      const password=focus==='password',a=phase*(password ? .32 : .42);
      const cx=password?field.x+field.w-65*scale:field.x+field.w/2,cy=password?field.y-22*scale:field.y+field.h/2;
      const rx=password?55*scale:field.w/2+24*scale,ry=password?18*scale:field.h/2+15*scale;
      return {x:cx+Math.cos(a)*rx,y:cy+Math.sin(a)*ry,z:password?9+Math.sin(a)*3:2,pace:password ? .65 : .8};
    }
    if(pointer&&now-pointer.time<2200)return {x:pointer.x,y:pointer.y,z:2};
    return {x:home.x+home.w*(.5+.31*Math.sin(phase*.31)),y:home.y+home.h*(.5+.27*Math.sin(phase*.47+.8)),z:2+Math.sin(phase*.6),pace:.8};
  }
  function startArrival() {
    bindStage();measure();refreshPending=false;
    if(toggle)toggle.hidden=true;
    if(paused||!renderer||!animal){staticRest();return;}
    state='arrival';elapsed=0;last=0;scale=animal.scale;
    arrival={from:Array.from(animal.trail.head),scale,duration:3.6};mountOverlay();wake();
  }
  function arrivalStep(dt) {
    elapsed+=dt;const t=Math.min(1,elapsed/arrival.duration),s=homeScale();
    motion.resting(destination,home.x+home.w/2,home.y+home.h/2,s);
    if(t<.35) {
      const p=motion.ease(t/.35),q=1-p,endX=destination[180],endY=destination[181];
      const bend=Math.min(90,Math.abs(endX-arrival.from[0])*.2);
      animal.trail.push(q*arrival.from[0]+p*endX,q*arrival.from[1]+p*endY-Math.sin(p*Math.PI)*bend,q*arrival.from[2]+p*destination[182]);
    }else {
      const p=(t-.35)/.65,index=(1-p)*60,i=Math.min(59,Math.floor(index)),a=index-i;
      animal.trail.push(destination[i*3]*(1-a)+destination[(i+1)*3]*a,destination[i*3+1]*(1-a)+destination[(i+1)*3+1]*a,destination[i*3+2]*(1-a)+destination[(i+1)*3+2]*a);
    }
    scale=arrival.scale+(s-arrival.scale)*motion.ease(t);animal.trail.sample(points,motion.length*scale);
    if(t>=1){points.set(destination);drawOverlay();staticRest();if(refreshPending){refreshPending=false;startRefresh();}return false;}
    return true;
  }
  function drawOverlay() {
    motion.uniforms(points,spine,scrollX,scrollY);renderer.draw(spine,scale,viewportWidth,viewportHeight,Math.min(devicePixelRatio||1,2));
  }
  async function startRefresh() {
    if(state==='arrival'){refreshPending=true;return;}
    if(state!=='rest'||paused||reduced.matches||document.hidden)return;
    state='refresh-loading';stage.dataset.motion=state;
    if(!await ensureRenderer()){fallback();return;}if(state!=='refresh-loading')return;
    measure();state='refresh';elapsed=0;last=0;scale=homeScale();
    // Paint the matching first frame before replacing the image: no blank flash.
    motion.resting(points,home.w/2,home.h/2,scale);motion.uniforms(points,spine);
    renderer.draw(spine,scale,home.w,home.h,Math.min(devicePixelRatio||1,2));
    canvas.className='python-local';canvas.hidden=false;stage.append(canvas);poster.hidden=true;wake();
  }
  function tick(now) {
    frame=0;if(document.hidden||paused||!renderer)return;if(dirty||state==='arrival')measure();
    const dt=last?Math.min((now-last)/1000,.04):1/60;last=now;phase+=dt;stage.dataset.motion=state;
    canvas.dataset.pose=state==='login'?(focus||(pointer&&now-pointer.time<2200?'follow':'idle')):state;
    if(state==='login') {
      animal.step(dt,loginGoal(now),Math.max(.55,Math.min(1.2,home.w/370)));scale=animal.scale;drawOverlay();
    }else if(state==='arrival') {
      if(!arrivalStep(dt))return;drawOverlay();
    }else if(state==='refresh') {
      elapsed+=dt;if(elapsed>=2.4){staticRest();return;}
      scale=homeScale();motion.refresh(points,elapsed/2.4,home.w/2,home.h/2,scale);motion.uniforms(points,spine);
      renderer.draw(spine,scale,home.w,home.h,Math.min(devicePixelRatio||1,2));
    }else return;
    wake();
  }
  function wake(){if(!frame&&!paused&&!document.hidden&&renderer&&['login','arrival','refresh'].includes(state))frame=requestAnimationFrame(tick);}
  function focused(){const el=document.activeElement;return el?.closest('.pwd-wrap')?'password':el?.id==='username'?'username':null;}
  document.addEventListener('pointermove',event=>{if(state==='login'&&event.pointerType!=='touch')pointer={x:event.clientX+scrollX,y:event.clientY+scrollY,time:performance.now()};},{passive:true});
  document.addEventListener('pointerleave',()=>{pointer=null;});
  document.addEventListener('focusin',()=>{if(state==='login'){focus=focused();dirty=true;}});
  document.addEventListener('focusout',()=>queueMicrotask(()=>{if(state==='login'){focus=focused();dirty=true;}}));
  document.addEventListener('click',event=>{if(event.target.closest('[data-python-refresh]'))startRefresh();});
  document.addEventListener('pytonazz:dashboard',()=>{try{sessionStorage.setItem('snake-phase',String(phase));}catch(_){}startArrival();});
  document.addEventListener('visibilitychange',()=>{
    cancelAnimationFrame(frame);frame=0;last=0;if(document.hidden&&state!=='login')staticRest();else wake();
  });
  addEventListener('resize',()=>{dirty=true;if(state!=='rest')wake();},{passive:true});
  addEventListener('scroll',()=>{if(state==='login'||state==='arrival'){dirty=true;wake();}},{passive:true,capture:true});
  reduced.addEventListener('change',()=>{
    paused=reduced.matches;cancelAnimationFrame(frame);frame=0;
    if(state!=='login')staticRest();else {bindStage();if(!paused)startLogin();else {canvas.hidden=true;poster.hidden=false;}}
  });
  canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();contextReady=false;renderer=null;loading=null;fallback();});
  canvas.addEventListener('webglcontextrestored',()=>{contextReady=true;if(state==='login')startLogin();});
  addEventListener('pagehide',()=>{cancelAnimationFrame(frame);frame=0;last=0;});
  addEventListener('pageshow',()=>{if(state==='login')wake();else if(state!=='rest')staticRest();});
  bindStage();focus=focused();if(state==='login')startLogin();else staticRest();
})();
