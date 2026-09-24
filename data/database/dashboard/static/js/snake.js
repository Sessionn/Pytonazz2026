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
  let gestureEnergy=0,gestureKind='nod',gestureCount=0;
  let poseFrom=null,poseTime=0,poseKind=null,typingUntil=0,typingField=null;
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
    canvas.style.cssText='';
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
    if(pointer&&now-pointer.time<2200)return {x:pointer.x,y:pointer.y,z:2,chase:true};
    return {x:home.x+home.w*(.5+.31*Math.sin(phase*.31)),y:home.y+home.h*(.5+.27*Math.sin(phase*.47+.8)),z:2+Math.sin(phase*.6),pace:.8};
  }
  function startArrival() {
    bindStage();measure();refreshPending=false;
    if(toggle)toggle.hidden=true;
    if(paused||!renderer||!animal){staticRest();return;}
    state='arrival';elapsed=0;last=0;scale=animal.scale;
    arrival={from:points.slice(),scale,duration:3.6};pointer=null;focus=null;mountOverlay();wake();
  }
  function arrivalStep(dt) {
    elapsed+=dt;const t=Math.min(1,elapsed/arrival.duration),s=homeScale();
    motion.resting(destination,home.x+home.w/2,home.y+home.h/2,s);
    scale=arrival.scale+(s-arrival.scale)*motion.ease(t);
    motion.transition(points,arrival.from,destination,t);
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
    paintRefresh(0);
    canvas.className='python-local';canvas.hidden=false;stage.append(canvas);poster.hidden=true;wake();
  }
  function paintRefresh(t) {
    const side=Math.max(home.w,home.h);
    // Square drawing surface allows the head to crawl around the resting body without clipping.
    canvas.style.width=side+'px';canvas.style.height=side+'px';
    canvas.style.left=(home.w-side)/2+'px';canvas.style.top=(home.h-side)/2+'px';
    motion.refresh(points,t,side/2,side/2,scale);motion.uniforms(points,spine);
    renderer.draw(spine,scale,side,side,Math.min(devicePixelRatio||1,2));
  }
  function tick(now) {
    frame=0;if(document.hidden||paused||!renderer)return;if(dirty||state==='arrival')measure();
    const dt=last?Math.min((now-last)/1000,.04):1/60;last=now;phase+=dt;stage.dataset.motion=state;
    canvas.dataset.pose=state==='login'?(focus||(pointer&&now-pointer.time<2200?'follow':'idle')):state;
    if(state==='login') {
      const active=focused()||(now<typingUntil?typingField:null);
      if(active!==focus){focus=active;dirty=true;measure();}
      if(focus&&field) {
        if(poseKind!==focus){poseFrom=points.slice();poseTime=0;poseKind=focus;}
        poseTime+=dt;scale=animal.scale;
        motion.fieldPose(destination,field,focus,scale);
        motion.transition(points,poseFrom,destination,Math.min(1,poseTime/1.7));
        canvas.dataset.pose=focus;
        canvas.dataset.settled=String(poseTime>=1.7);
      }else {
        if(poseKind){animal=new motion.Animal(points,scale);animal.speed=0;poseKind=null;pointer=null;}
        canvas.dataset.settled='false';
        animal.step(dt,loginGoal(now),Math.max(.55,Math.min(1.2,home.w/370)));scale=animal.scale;
      }
      gestureEnergy*=Math.exp(-dt*2.8);
      motion.gesture(points,phase,gestureKind,gestureEnergy,scale);
      canvas.dataset.gesture=gestureEnergy>.05?gestureKind:'none';drawOverlay();
    }else if(state==='arrival') {
      if(!arrivalStep(dt))return;drawOverlay();
    }else if(state==='refresh') {
      elapsed+=dt;if(elapsed>=4.2){staticRest();return;}
      scale=homeScale();paintRefresh(elapsed/4.2);
    }else return;
    wake();
  }
  function wake(){if(!frame&&!paused&&!document.hidden&&renderer&&['login','arrival','refresh'].includes(state))frame=requestAnimationFrame(tick);}
  function focused(){const el=document.activeElement;return el?.closest('.pwd-wrap')?'password':el?.id==='username'?'username':null;}
  document.addEventListener('pointermove',event=>{if(state==='login'&&!focused()&&performance.now()>=typingUntil&&event.pointerType!=='touch')pointer={x:event.clientX+scrollX,y:event.clientY+scrollY,time:performance.now()};},{passive:true});
  document.addEventListener('pointerleave',()=>{pointer=null;});
  function updateFocus(){if(state==='login'){const next=focused();if(next!==focus){gestureEnergy=0;}focus=next;if(next)pointer=null;dirty=true;}}
  document.addEventListener('focusin',updateFocus);
  document.addEventListener('focusout',()=>queueMicrotask(updateFocus));
  document.addEventListener('beforeinput',event=>{
    if(state!=='login'||paused||!['username','password'].includes(event.target.id))return;
    typingField=event.target.id;typingUntil=performance.now()+1000;pointer=null;
    // Only an input event and field identity are used; never key/data/value.
    if(gestureEnergy<.15)gestureKind=event.target.id==='password'?'guard':['nod','look','ripple'][gestureCount++%3];
    gestureEnergy=Math.min(1,gestureEnergy+.4);
  });
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
