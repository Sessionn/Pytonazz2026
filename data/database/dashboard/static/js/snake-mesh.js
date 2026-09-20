/* Blender-exported python: immutable mesh and 2K maps, deformed on the GPU.
 * Local axes: x towards the nose, y across the back, z above the page.
 * Original assets are served locally. No CDN or per-frame geometry allocation. */
window.PythonMesh = (() => {
  const assetRoot = '/static/models/python/';
  async function loadMesh() {
    const response = await fetch(assetRoot + 'python.mesh', {signal:AbortSignal.timeout(20000)});
    if (!response.ok) throw new Error('Python model unavailable');
    const buffer = await response.arrayBuffer();
    const header = new DataView(buffer);
    if (buffer.byteLength < 12 || header.getUint32(0, true) !== 0x31545950) throw new Error('Invalid python model');
    const count = header.getUint32(4, true), length = header.getUint32(8, true);
    if (!count || count > 65535 || !length || buffer.byteLength !== 12 + count * 40 + length * 2) throw new Error('Invalid model bounds');
    return { vertices: new Float32Array(buffer, 12, count * 10), indices: new Uint16Array(buffer, 12 + count * 40, length) };
  }
  function loadImage(name) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      const timer=setTimeout(()=>{image.onload=null;image.onerror=null;image.src='';reject(new Error('Python texture timeout'));},20000);
      image.onload = () => {clearTimeout(timer);resolve(image);};
      image.onerror = () => {clearTimeout(timer);reject(new Error('Python texture unavailable'));};
      image.src = assetRoot + name;
    });
  }

  const vertexShader = `
    precision highp float;
    attribute vec3 position, normal;
    attribute float along, material;
    attribute vec2 uv;
    uniform vec4 spine[64];
    uniform vec2 viewport;
    uniform float size, shadow;
    varying vec3 N, T;
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
      if(shadow<.5) p.y-=z*.35;
      if(shadow>.5){p+=vec2(2.,5.)*size+vec2(0.,max(0.,z)*.16);z=-100.;}
      N=normalize(vec3(forward*normal.x+side*normal.y,normal.z)); T=vec3(forward*(material<.5?-1.:1.),0.); UV=uv; M=material;
      gl_Position=vec4(p.x/viewport.x*2.-1.,1.-p.y/viewport.y*2.,-z/400.,1.);
    }`;

  const fragmentShader = `
    precision highp float;
    varying vec3 N, T;
    varying vec2 UV;
    varying float M;
    uniform float shadow;
    uniform sampler2D skinMap, normalMap;
    float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
    void main(){
      if(shadow>.5){gl_FragColor=vec4(.015,.01,.005,.24);return;}
      vec3 n=normalize(N), color;
      float rough=.36;
      if(M<1.5){
        vec4 surface=texture2D(skinMap,UV);
        color=pow(surface.rgb,vec3(2.2));
        vec3 bump=texture2D(normalMap,UV).xyz*2.-1.;
        vec3 tangent=normalize(T-n*dot(T,n));
        vec3 bitangent=normalize(cross(n,tangent));
        n=normalize(tangent*bump.x+bitangent*bump.y+n*bump.z);
        rough=.48;
      }else if(M<2.5){
        float streak=sin(UV.y*185.)*.5+.5;
        color=mix(vec3(.015,.008,.002),vec3(.09,.045,.015),streak); rough=.12;
      }else if(M<3.5){color=vec3(.006,.008,.006);rough=.16;}
      else {color=vec3(.85,.91,.86);rough=.08;}
      vec3 light=normalize(vec3(-.35,-.5,1.));
      float diffuse=max(dot(n,light),0.);
      vec3 halfVector=normalize(light+vec3(0.,0.,1.));
      float spec=pow(max(dot(n,halfVector),0.),mix(100.,18.,rough));
      float rim=pow(1.-max(n.z,0.),3.)*.1;
      color=color*(.45+diffuse*.85)+vec3(.85,.91,1.)*(spec*.045+rim*.15);
      gl_FragColor=vec4(pow(color,vec3(1./2.2)),1.);
    }`;

  async function create(canvas) {
    const gl = canvas.getContext('webgl', { alpha: true, antialias: true, powerPreference: 'default' });
    if (!gl) return null;
    const [mesh, skin, normals] = await Promise.all([loadMesh(), loadImage('skin.webp'), loadImage('normal.webp')]);
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
    const textures = [];
    for (const [unit, name, image] of [[0,'skinMap',skin],[1,'normalMap',normals]]) {
      const texture = gl.createTexture(); textures.push(texture);
      gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,image);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR_MIPMAP_LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
      gl.generateMipmap(gl.TEXTURE_2D);
      const anisotropic=gl.getExtension('EXT_texture_filter_anisotropic');
      if(anisotropic) gl.texParameterf(gl.TEXTURE_2D,anisotropic.TEXTURE_MAX_ANISOTROPY_EXT,Math.min(4,gl.getParameter(anisotropic.MAX_TEXTURE_MAX_ANISOTROPY_EXT)));
      gl.uniform1i(gl.getUniformLocation(program,name),unit);
    }
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
      dispose() { textures.forEach(texture=>gl.deleteTexture(texture)); gl.deleteBuffer(vertexBuffer); gl.deleteBuffer(indexBuffer); gl.deleteProgram(program); }
    };
  }
  return { create };
})();
