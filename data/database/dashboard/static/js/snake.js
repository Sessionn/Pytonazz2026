/* Procedural 3D mascot. No network requests, libraries or form-value access. */
(() => {
  const stage = document.querySelector('.snake-stage');
  if (!stage) return;
  const canvas = stage.querySelector('canvas');
  const toggle = stage.querySelector('button');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let phase = 0, paused = reduced.matches, frame = 0, last = 0, pulse = 0;
  let pointer = [0, 0];
  try { phase = Number(sessionStorage.getItem('snake-phase')) || 0; paused ||= sessionStorage.getItem('snake-paused') === '1'; } catch (_) {}
  const gl = canvas.getContext('webgl', { alpha: true, antialias: true, powerPreference: 'low-power' });
  function fallback() {
    canvas.hidden = true;
    const shape = document.createElement('div'); shape.className = 'snake-fallback'; shape.textContent = '〰'; shape.setAttribute('aria-hidden', 'true'); stage.append(shape);
    toggle.hidden = true;
  }
  if (!gl) { fallback(); return; }
  function shader(type, source) {
    const s = gl.createShader(type); gl.shaderSource(s, source); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error('shader');
    return s;
  }
  let program;
  try {
    program = gl.createProgram();
    gl.attachShader(program, shader(gl.VERTEX_SHADER, `
      attribute vec3 position; attribute vec3 normal; attribute vec3 color;
      uniform float aspect; varying vec3 n; varying vec3 c; varying vec3 p;
      void main(){ n=normal; c=color; p=position; gl_Position=vec4(position.x/aspect, position.y, -position.z*.2, 1.25-position.z*.12); }
    `));
    gl.attachShader(program, shader(gl.FRAGMENT_SHADER, `
      precision mediump float; varying vec3 n; varying vec3 c; varying vec3 p;
      void main(){vec3 nn=normalize(n); float d=max(dot(nn,normalize(vec3(-.4,.8,1.))),0.);
      float shine=pow(max(dot(reflect(-normalize(vec3(-.4,.8,1.)),nn),vec3(0.,0.,1.)),0.),28.);
      vec3 skin=c;
      if(c.r>.2 && c.g>.15 && c.b<.5){
        float patches=sin(p.x*16.+sin(p.y*11.)*1.6)*cos(p.y*13.+p.z*9.);
        float edge=smoothstep(.04,.2,patches);
        skin=mix(vec3(.68,.49,.25),vec3(.13,.085,.055),edge);
        vec2 scales=vec2(p.x*125.,atan(n.y,n.z)*15.);
        scales.x+=mod(floor(scales.y),2.)*.5;
        vec2 cell=fract(scales)-.5;
        float seam=smoothstep(.32,.5,length(cell*vec2(.85,1.2)));
        skin*=1.-seam*.24;
        skin+=vec3(.045)*pow(max(0.,1.-length(cell)*2.),3.);
      }
      gl_FragColor=vec4(skin*(.33+.67*d)+vec3(.24)*shine,1.);}
    `));
    gl.linkProgram(program); if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('link');
  } catch (_) { fallback(); return; }
  gl.useProgram(program); gl.enable(gl.DEPTH_TEST);
  const buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  ['position','normal','color'].forEach((name,i) => { const a=gl.getAttribLocation(program,name); gl.enableVertexAttribArray(a); gl.vertexAttribPointer(a,3,gl.FLOAT,false,36,i*12); });
  const aspect = gl.getUniformLocation(program,'aspect');
  function center(u) { return [-1.25+u*2.5+Math.sin(phase*.4)*.1+pointer[0]*.15, Math.sin(u*9-phase)*(.25+pulse*.04)+pointer[1]*.12, Math.cos(u*7-phase)*.13]; }
  function geometry() {
    const data=[]; const rings=192, sides=24;
    const vert=(u,a) => {
      const c=center(u), next=center(u+.001), angle=Math.atan2(next[1]-c[1],next[0]-c[0]);
      const radius=(.12+.08*Math.sin(Math.PI*u))*Math.pow(1-u,.55)+.002;
      const n=[-Math.sin(angle)*Math.cos(a),Math.cos(angle)*Math.cos(a),Math.sin(a)];
      const band=Math.floor(u*46)%2 ? .87:1;
      return [...c.map((v,i)=>v+n[i]*radius),...n,.58*band,.43*band,.24*band];
    };
    for(let i=0;i<rings;i++) for(let j=0;j<sides;j++) {
      const a=j*2*Math.PI/sides,b=(j+1)*2*Math.PI/sides;
      const p=vert(i/rings,a),q=vert((i+1)/rings,a),r=vert((i+1)/rings,b),s=vert(i/rings,b);
      data.push(...p,...q,...r,...p,...r,...s);
    }
    function sphere(c,r,color,stretch=[1,1,1]) {
      const v=(a,b)=>{const n=[Math.sin(a)*Math.cos(b),Math.cos(a),Math.sin(a)*Math.sin(b)];return [...c.map((x,i)=>x+n[i]*r*stretch[i]),...n,...color];};
      for(let i=0;i<8;i++)for(let j=0;j<12;j++) { const a=i*Math.PI/8,b=j*Math.PI/6,aa=(i+1)*Math.PI/8,bb=(j+1)*Math.PI/6; data.push(...v(a,b),...v(aa,b),...v(aa,bb),...v(a,b),...v(aa,bb),...v(a,bb)); }
    }
    const h=center(0); sphere(h,.17,[.58,.43,.24],[1.4,.8,.68]);
    for(const side of [-1,1]) { const eye=[h[0]-.105,h[1]+side*.085,h[2]+.085]; sphere(eye,.025,[.19,.14,.035]); sphere([eye[0],eye[1],eye[2]+.02],.015,[.01,.01,.015],[.35,1,.5]); sphere([eye[0]-.006,eye[1]+.006,eye[2]+.027],.005,[1,1,1]); }
    return new Float32Array(data);
  }
  function draw(now=0) {
    frame=0;
    if(document.hidden) return;
    if(now-last>=33 || paused || !last) {
      const dt=last ? Math.min((now-last)/1000,.08):0; last=now;
      if(!paused) { phase+=dt*(1.15+pulse); pulse*=.95; }
      const dpr=Math.min(devicePixelRatio||1,2), w=Math.max(1,Math.floor(stage.clientWidth*dpr)), h=Math.max(1,Math.floor(stage.clientHeight*dpr));
      if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
      gl.viewport(0,0,w,h); gl.clearColor(0,0,0,0); gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT); gl.uniform1f(aspect,w/h);
      const vertices=geometry(); gl.bufferData(gl.ARRAY_BUFFER,vertices,gl.DYNAMIC_DRAW); gl.drawArrays(gl.TRIANGLES,0,vertices.length/9);
    }
    if(!paused) frame=requestAnimationFrame(draw);
  }
  function refresh(){ if(!frame) draw(performance.now()); }
  function label(){ toggle.textContent=paused?'▶':'Ⅱ'; toggle.setAttribute('aria-label',paused?'Riprendi animazione':'Pausa animazione'); toggle.setAttribute('aria-pressed',String(paused)); }
  toggle.addEventListener('click',()=>{paused=!paused;label();try{sessionStorage.setItem('snake-paused',paused?'1':'0');}catch(_){}refresh();});
  document.addEventListener('pointermove',e=>{pointer=[(e.clientX/innerWidth-.5)*2,(.5-e.clientY/innerHeight)*2];},{passive:true});
  document.addEventListener('click',e=>{if(e.target.closest('button,a,select')){pulse=.7;refresh();}});
  document.addEventListener('focusin',()=>{pulse=.4;refresh();});
  document.addEventListener('visibilitychange',()=>{last=0;if(document.hidden){cancelAnimationFrame(frame);frame=0;}else refresh();});
  reduced.addEventListener('change',()=>{paused=reduced.matches;label();refresh();});
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();cancelAnimationFrame(frame);frame=0;paused=true;fallback();});
  addEventListener('pagehide',()=>{try{sessionStorage.setItem('snake-phase',String(phase));}catch(_){}cancelAnimationFrame(frame);});
  new ResizeObserver(refresh).observe(stage);
  label();refresh();
})();
