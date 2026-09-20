/* Original python mesh: immutable indexed surface, deformed on the GPU.
 * Local axes: x towards the nose, y across the back, z above the page.
 * No external model, texture, library, or per-frame geometry allocation. */
window.PythonMesh = (() => {
  function build() {
    const vertices = [], indices = [];
    function vertex(x, y, z, nx, ny, nz, along, u, v, material) {
      vertices.push(x, y, z, nx, ny, nz, along, u, v, material);
    }
    function surface(rows, sides, point) {
      const base = vertices.length / 10;
      for (let i = 0; i <= rows; i++) {
        for (let j = 0; j <= sides; j++) point(i / rows, j / sides);
      }
      for (let i = 0; i < rows; i++) for (let j = 0; j < sides; j++) {
        const a = base + i * (sides + 1) + j, b = a + sides + 1;
        indices.push(a, b, a + 1, a + 1, b, b + 1);
      }
    }
    surface(384, 64, (u, v) => {
      const a = v * Math.PI * 2;
      // Narrow neck, substantial muscular torso, continuously tapering tail.
      const r = (7 + 9 * Math.sin(Math.PI * Math.min(1, u * 1.3))) * Math.pow(1 - u, .72) + .12;
      const side = Math.cos(a), top = Math.sin(a);
      vertex(0, side * r, top * r * .76, 0, side, top / .76, u, u, v, 0);
    });
    // Sculpted wedge: broad rear jaw, orbital ridges, narrowing flat snout.
    surface(64, 64, (u, v) => {
      const a = v * Math.PI * 2, x = -7 + u * 37;
      const cap = Math.min(1, Math.sqrt(Math.max(0,1-u)*20));
      const width = (6 + 7.5 * Math.sin(Math.PI * u)) * cap;
      const top = Math.sin(a), side = Math.cos(a);
      const orbital = Math.exp(-Math.pow((u - .63) * 10, 2)) * 1.8 * Math.abs(side);
      vertex(x, width * side, 1 + top * (top > 0 ? 7 + orbital : 3.7)*cap,
        .13, side, top * 1.6, 0, u, v, 1);
    });
    function ellipsoid(x, y, z, rx, ry, rz, material) {
      surface(20, 32, (u, v) => {
        const a = u * Math.PI, b = v * Math.PI * 2;
        const nx = Math.sin(a) * Math.cos(b), ny = Math.sin(a) * Math.sin(b), nz = Math.cos(a);
        vertex(x + nx * rx, y + ny * ry, z + nz * rz, nx / rx, ny / ry, nz / rz, 0, u, v, material);
      });
    }
    for (const side of [-1, 1]) {
      ellipsoid(16, side * 9.2, 9.2, 2.8, 2.15, 1.5, 2); // amber iris
      ellipsoid(16, side * 9.2, 10.55, .5, 1.65, .36, 3); // vertical pupil
      ellipsoid(16.7, side * 8.6, 10.95, .38, .34, .16, 4); // corneal reflection
      ellipsoid(26.1, side * 4.2, 5.5, .8, .65, .3, 3); // nostrils
      for (let i = 0; i < 5; i++) ellipsoid(7 + i * 3.6, side * (11 - i * .55), 1.6, .6, .3, .45, 3);
    }
    return { vertices: new Float32Array(vertices), indices: new Uint16Array(indices) };
  }

  const vertexShader = `
    precision highp float;
    attribute vec3 position, normal;
    attribute float along, material;
    attribute vec2 uv;
    uniform vec4 spine[64];
    uniform vec2 viewport;
    uniform float size, shadow;
    varying vec3 N;
    varying vec2 UV;
    varying float M;
    vec3 curve(float t) {
      float f = clamp(t,0.,1.) * 60.;
      int i = int(f); float a = fract(f);
      vec3 p0=spine[i].xyz, p1=spine[i+1].xyz, p2=spine[i+2].xyz, p3=spine[i+3].xyz;
      return .5*((2.*p1)+(-p0+p2)*a+(2.*p0-5.*p1+4.*p2-p3)*a*a+(-p0+3.*p1-3.*p2+p3)*a*a*a);
    }
    void main() {
      vec3 c=curve(along);
      vec3 d=curve(min(1.,along+.002))-curve(max(0.,along-.002));
      vec2 forward=-normalize(d.xy+vec2(.0001));
      vec2 side=vec2(-forward.y,forward.x);
      vec2 p=c.xy+(forward*position.x+side*position.y)*size;
      float z=c.z+position.z*size;
      if(shadow>.5){p+=vec2(2.,5.)*size+vec2(0.,max(0.,z)*.16);z=-100.;}
      N=normalize(vec3(forward*normal.x+side*normal.y,normal.z)); UV=uv; M=material;
      gl_Position=vec4(p.x/viewport.x*2.-1.,1.-p.y/viewport.y*2.,-z/400.,1.);
    }`;

  const fragmentShader = `
    precision highp float;
    varying vec3 N;
    varying vec2 UV;
    varying float M;
    uniform float shadow;
    float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
    void main(){
      if(shadow>.5){gl_FragColor=vec4(.015,.01,.005,.24);return;}
      vec3 n=normalize(N), color;
      float rough=.36;
      if(M<1.5){
        bool head=M>.5;
        vec2 q=vec2(UV.x*31.,UV.y*5.);
        q.x+=sin(q.y*2.1)*.65;
        vec2 patchCell=floor(q), f=fract(q)-.5;
        float noise=hash(patchCell);
        float patch=length(f*vec2(1.1,.83)) + sin(UV.x*417.+UV.y*91.)*.04;
        float gold=1.-smoothstep(.28,.37,patch);
        color=mix(vec3(.10,.063,.033),vec3(.52,.35,.16),gold);
        color+=vec3(.11,.075,.03)*exp(-pow((patch-.32)*22.,2.));
        color*=.88+.22*noise;
        if(head){
          color=mix(vec3(.27,.17,.075),vec3(.46,.32,.15),sin(UV.y*6.28318)*.5+.5);
          float stripe=exp(-pow((sin(UV.y*6.28318)-.35)*9.,2.));
          color*=1.-stripe*.65;
        }
        // Cream ventral plates; longitudinal mask stays attached to the mesh.
        float belly=1.-smoothstep(0.,.18,sin(UV.y*6.28318)+.65);
        color=mix(color,vec3(.67,.57,.38),belly);
        vec2 cell=vec2(UV.x*(head?27.:470.),UV.y*(head?30.:64.));
        cell.x+=mod(floor(cell.y),2.)*.5;
        vec2 tile=fract(cell)-.5;
        float edge=length(tile*vec2(.83,1.12));
        float groove=smoothstep(.36,.48,edge);
        float variation=hash(floor(cell));
        color*=.86+.2*variation;
        color*=1.-groove*.32;
        n=normalize(n+vec3(tile.x,tile.y,0.)*(1.-groove)*.25);
        rough=.27+groove*.25;
        // Jaw seam follows the sculpt, never the screen coordinates.
        if(head) color*=1.-.55*exp(-pow((sin(UV.y*6.28318)+.12)*38.,2.));
      }else if(M<2.5){
        float streak=sin(UV.y*185.)*.5+.5;
        color=mix(vec3(.22,.11,.025),vec3(.7,.44,.1),streak); rough=.12;
      }else if(M<3.5){color=vec3(.006,.008,.006);rough=.16;}
      else {color=vec3(.85,.91,.86);rough=.08;}
      vec3 light=normalize(vec3(-.35,-.5,1.));
      float diffuse=max(dot(n,light),0.);
      vec3 halfVector=normalize(light+vec3(0.,0.,1.));
      float spec=pow(max(dot(n,halfVector),0.),mix(100.,18.,rough));
      float rim=pow(1.-max(n.z,0.),3.)*.1;
      color=color*(.28+diffuse*.85)+vec3(.85,.91,1.)*(spec*.3+rim);
      gl_FragColor=vec4(pow(color,vec3(.88)),1.);
    }`;

  function create(canvas) {
    const gl = canvas.getContext('webgl', { alpha: true, antialias: true, powerPreference: 'default' });
    if (!gl) return null;
    const compile = (type, source) => {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source); gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
      return shader;
    };
    const program = gl.createProgram();
    gl.attachShader(program, compile(gl.VERTEX_SHADER, vertexShader));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, fragmentShader));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);
    const mesh = build();
    const vertexBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vertexBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, mesh.vertices, gl.STATIC_DRAW);
    const indexBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, mesh.indices, gl.STATIC_DRAW);
    let offset = 0;
    for (const [name, count] of [['position',3],['normal',3],['along',1],['uv',2],['material',1]]) {
      const location = gl.getAttribLocation(program, name);
      gl.enableVertexAttribArray(location); gl.vertexAttribPointer(location,count,gl.FLOAT,false,40,offset*4);
      offset += count;
    }
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND); gl.blendFuncSeparate(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA,gl.ONE,gl.ONE_MINUS_SRC_ALPHA);
    const locations = Object.fromEntries(['spine','viewport','size','shadow'].map(n => [n,gl.getUniformLocation(program,n)]));
    return {
      clear() { gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT); },
      draw(spine, size, width, height, dpr) {
        const w = Math.round(width*dpr), h = Math.round(height*dpr);
        if(canvas.width!==w || canvas.height!==h){canvas.width=w;canvas.height=h;gl.viewport(0,0,w,h);}
        gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
        gl.uniform4fv(locations.spine,spine);
        gl.uniform2f(locations.viewport,width,height); gl.uniform1f(locations.size,size);
        gl.uniform1f(locations.shadow,1);
        gl.drawElements(gl.TRIANGLES,mesh.indices.length,gl.UNSIGNED_SHORT,0);
        gl.uniform1f(locations.shadow,0);
        gl.drawElements(gl.TRIANGLES,mesh.indices.length,gl.UNSIGNED_SHORT,0);
      },
      dispose() { gl.deleteBuffer(vertexBuffer); gl.deleteBuffer(indexBuffer); gl.deleteProgram(program); }
    };
  }
  return { create };
})();
