"""Build the original ball-python asset in Blender 4.5 (no external assets).

blender --background --factory-startup --python tools/blender/build_python.py
Outputs: editable .blend, GLB, browser mesh, baked 2K skin/normal maps, portrait.
The web mesh and master use the same anatomical profile and UV layout.
"""
from pathlib import Path
import json
import math
import struct

import bpy
import numpy as np
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'data/database/dashboard/static/models/python'
SOURCE = ROOT / 'assets/python'
OUT.mkdir(parents=True, exist_ok=True)
SOURCE.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)


def image(name, pixels, path, noncolor=False):
    h, w = pixels.shape[:2]
    im = bpy.data.images.new(name, w, h, alpha=True)
    if noncolor:
        im.colorspace_settings.name = 'Non-Color'
    im.pixels.foreach_set(pixels.astype(np.float32).ravel())
    im.filepath_raw = str(path)
    im.file_format = 'PNG'
    im.save()
    im.pack()
    return im


def skin_atlas():
    n = 2048
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) / (n - 1)
    head = y >= .75
    v = np.where(head, (y - .75) * 4, y / .75)
    # Broken saddle markings and irregular flank rosettes, instead of a grid.
    longitudinal = x * 27 + np.sin(v * 18) * .25
    warp = np.sin(x * 133 + v * 23) * .065 + np.sin(x * 347 - v * 37) * .035
    cx = np.mod(longitudinal, 1) - .5
    flank = np.abs(np.sin(v * math.tau))
    spot = np.sqrt((cx * 1.55) ** 2 + ((flank - .5) * 1.15) ** 2) + warp
    island = np.clip((.55 - spot) * 18, 0, 1)
    border = np.exp(-((spot - .51) * 28) ** 2)
    dark = np.array([.12, .074, .038])
    honey = np.array([.48, .32, .14])
    rgb = dark + island[..., None] * (honey - dark)
    rgb += border[..., None] * np.array([.12, .085, .035])
    flecks = (np.sin(x * 732 + v * 282) * np.sin(x * 413 - v * 198))
    rgb *= (1 + flecks * .065)[..., None]
    ventral = np.clip((-np.sin(v * math.tau) - .58) * 7, 0, 1)
    cream = np.array([.67, .57, .39])
    rgb = rgb * (1 - ventral[..., None]) + cream * ventral[..., None]
    # Crown, postocular stripe, cream labials. Large plates on the head.
    crown = np.empty_like(rgb)
    crown[:] = [.23, .145, .065]
    stripe = np.exp(-((np.sin(v * math.tau) - .27) * 9) ** 2)
    crown *= (1 - stripe * .76)[..., None]
    labial = np.clip((.17 - np.sin(v * math.tau)) * 8, 0, 1)
    crown = crown * (1-labial[..., None]) + cream * labial[..., None]
    rgb = np.where(head[..., None], crown, rgb)
    rows = np.where(head, 16, 52)
    cols = np.where(head, 18, 330)
    sy = v * rows
    sx = x * cols + (np.floor(sy) % 2) * .5
    a, b = np.mod(sx, 1)-.5, np.mod(sy, 1)-.5
    radius = np.sqrt((a*.94)**2+(b*1.1)**2)
    dome = np.clip(1-(radius/.48)**2,0,1)**.65
    seam = np.clip((radius-.38)*10,0,1)
    height = dome*.6
    # Cranial shields: irregular flat tiles with narrow sutures, not round beads.
    px=x*18;py=v*16
    nearest=np.full_like(x,10);second=np.full_like(x,10)
    for ox in [-1,0,1]:
        for oy in [-1,0,1]:
            gx=np.floor(px)+ox;gy=np.floor(py)+oy
            jx=np.mod(np.sin(gx*127.1+gy*311.7)*43758.5453,1)
            jy=np.mod(np.sin(gx*269.5+gy*183.3)*21823.152,1)
            distance=(px-gx-.2-jx*.6)**2+(py-gy-.2-jy*.6)**2
            second=np.minimum(second,np.maximum(nearest,distance))
            nearest=np.minimum(nearest,distance)
    plate=np.clip((np.sqrt(second)-np.sqrt(nearest))*16,0,1)
    height=np.where(head,plate*.12,height)
    seam=np.where(head,1-plate,seam)
    # Ventral scutes are broad, transverse shields.
    shield = np.clip(1-(np.mod(x*290,1)-.5)**2*4,0,1)
    height = height*(1-ventral) + shield*.25*ventral
    rgb *= (1-seam*.13)[..., None]
    rgb *= (.94+.06*np.sin(np.floor(sx)*19+np.floor(sy)*31))[..., None]
    rough = .43 + seam*.18 + ventral*.08
    color = np.concatenate([np.clip(rgb,0,1), rough[...,None]],axis=2)
    dy, dx = np.gradient(height)
    normals = np.stack([-dx*1.5,-dy*1.5,np.ones_like(dx)],axis=2)
    normals /= np.linalg.norm(normals,axis=2)[...,None]
    normal = np.concatenate([normals*.5+.5,np.ones_like(dx)[...,None]],axis=2)
    return image('Python_2K_Albedo_Roughness',color,OUT/'skin.png'), image('Python_2K_Normal',normal,OUT/'normal.png',True)


skin, normal_map = skin_atlas()
mat = bpy.data.materials.new('Python skin • baked 2K scales')
mat.use_nodes = True
nodes, links = mat.node_tree.nodes, mat.node_tree.links
bsdf = nodes.get('Principled BSDF')
tex = nodes.new('ShaderNodeTexImage'); tex.image=skin
normal_tex=nodes.new('ShaderNodeTexImage'); normal_tex.image=normal_map
normal=nodes.new('ShaderNodeNormalMap')
links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
links.new(tex.outputs['Alpha'],bsdf.inputs['Roughness'])
links.new(normal_tex.outputs['Color'],normal.inputs['Color'])
links.new(normal.outputs['Normal'],bsdf.inputs['Normal'])
bsdf.inputs['IOR'].default_value=1.46
bsdf.inputs['Coat Weight'].default_value=.07


def solid(name, color, roughness):
    m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
    p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*color,1)
    p.inputs['Roughness'].default_value=roughness
    return m


materials=[mat,mat,solid('Bronze iris',(.08,.045,.016),.12),solid('Pupil and recessed pits',(.003,.002,.001),.11),solid('Cornea highlight',(.7,.82,.85),.07)]
rest=bpy.data.collections.new('Python • production rest mesh');bpy.context.scene.collection.children.link(rest)
master=bpy.data.collections.new('Python • high resolution sculpt');bpy.context.scene.collection.children.link(master)
records=[]


def surface(name, rows, sides, point, material, collection=rest, record=True):
    verts=[];uvs=[];alongs=[];faces=[]
    for i in range(rows+1):
        for j in range(sides+1):
            u,v=i/rows,j/sides
            xyz, along=point(u,v)
            verts.append(xyz);alongs.append(along)
            uvs.append((u,v*.75) if material==0 else (u,.75+v*.25))
    for i in range(rows):
        for j in range(sides):
            a=i*(sides+1)+j;b=a+sides+1
            faces.append((a,a+1,b+1,b))
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(verts,[],faces);mesh.update()
    obj=bpy.data.objects.new(name,mesh);collection.objects.link(obj)
    obj.data.materials.append(materials[material])
    layer=mesh.uv_layers.new(name='Skin atlas')
    for poly in mesh.polygons:
        poly.use_smooth=True
        for loop in poly.loop_indices:layer.data[loop].uv=uvs[mesh.loops[loop].vertex_index]
    # Explicitly recalculate orientation for rings and ellipsoids alike.
    bpy.context.view_layer.objects.active=obj;obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT');bpy.ops.mesh.normals_make_consistent(inside=False);bpy.ops.object.mode_set(mode='OBJECT');obj.select_set(False)
    if record:records.append((obj,uvs,alongs,material))
    return obj


def body(u,v, sculpt=False):
    a=v*math.tau
    # Gradual neck, muscular trunk, long pointed tail.
    radius=(7.0+11*math.sin(math.pi*min(1,u*1.22)))*max(0,1-u)**.68+.05
    c,s=math.cos(a),math.sin(a)
    z=radius*s*(.78 if s>0 else .6)
    if sculpt:
        sx=u*330+(math.floor(v*52)%2)*.5;sy=v*52
        r=math.hypot((sx%1-.5)*.94,(sy%1-.5)*1.1)
        bump=max(0,1-(r/.48)**2)**.65*.18
        radius+=bump;z+=bump*s
    return (-u*540,radius*c,z),u


profile_x=np.array([-11,-7,0,7,14,21,27,31,32])
profile_y=np.array([6.8,8.0,11.2,13.4,12.0,9.6,7.4,4.4,.05])
profile_z=np.array([5.5,6.3,7.5,8.7,7.8,6.0,4.3,2.7,.05])


def profile(values, x):
    i=max(0,min(len(profile_x)-2,int(np.searchsorted(profile_x,x)-1)))
    span=profile_x[i+1]-profile_x[i];t=(x-profile_x[i])/span
    slopes=np.gradient(values,profile_x)
    return float((2*t**3-3*t*t+1)*values[i]+(t**3-2*t*t+t)*span*slopes[i]
                 +(-2*t**3+3*t*t)*values[i+1]+(t**3-t*t)*span*slopes[i+1])


def head(u,v,sculpt=False):
    x=-11+u*43;a=v*math.tau;c,s=math.cos(a),math.sin(a)
    width=profile(profile_y,x);height=profile(profile_z,x)
    # Supraocular ridge and nasal bridge are part of the actual mesh silhouette.
    orbit=math.exp(-((x-15)/4.5)**2)*math.exp(-((abs(c)-.78)/.2)**2)*1.7
    z=1+s*(height if s>0 else 3.5)+max(s,0)*orbit
    y=c*width
    # Labial fold and the mouth are modelled depressions, not a black decal.
    mouth=math.exp(-((s+.10)*25)**2)*.52
    y*=1-mouth/width
    if sculpt:
        sx=u*26+(math.floor(v*22)%2)*.5;sy=v*22
        r=math.hypot((sx%1-.5)*.94,(sy%1-.5)*1.1)
        ridge=max(0,1-(r/.48)**2)**.65*.13
        y+=c*ridge;z+=s*ridge
    return (x,y,z),0


surface('Body • UV production',320,56,body,0)
surface('Head • cranial and labial anatomy',96,64,head,1)
surface('Body • sculpted overlapping scales',1320,112,lambda u,v:body(u,v,True),0,master,False)
surface('Head • sculpted shields',260,160,lambda u,v:head(u,v,True),1,master,False)


def ellipsoid(name,center,radii,material,rows=20,sides=32):
    def point(u,v):
        a=u*math.pi;b=v*math.tau
        return tuple(center[i]+radii[i]*n for i,n in enumerate((math.sin(a)*math.cos(b),math.sin(a)*math.sin(b),math.cos(a)))),0
    return surface(name,rows,sides,point,material)


for side in [-1,1]:
    # Eyes sit on the lateral orbital shelf; separate corneal and iris volumes.
    ellipsoid(f'Eye {side} • bronze', (15.7,side*9.8,4.6),(2.0,1.8,1.9),2)
    ellipsoid(f'Eye {side} • slit', (15.8,side*10.5,6.2),(.65,1.1,.42),3)
    ellipsoid(f'Eye {side} • catchlight',(16.35,side*10.15,6.62),(.2,.19,.12),4,12,16)
    ellipsoid(f'Nostril {side}',(27,side*5.0,4.5),(.7,.65,.3),3,12,16)
    for i in range(5):
        x=5+i*4.2
        w=profile(profile_y,x)
        ellipsoid(f'Labial pit {side}/{i}',(x,side*(w-.08),.6),(.75,.34,.55),3,12,16)

# Export compact immutable mesh data with the same attributes as the web rig.
packed=[];indices=[]
for obj,uvs,alongs,material in records:
    mesh=obj.data;mesh.calc_loop_triangles();base=len(packed)//10
    for i,vert in enumerate(mesh.vertices):
        x,y,z=vert.co;n=vert.normal
        packed.extend((0 if material==0 else x,y,z,*n,alongs[i],*uvs[i],material))
    for triangle in mesh.loop_triangles:indices.extend(base+i for i in triangle.vertices)
vertex_count=len(packed)//10
assert vertex_count<65536, vertex_count
binary=struct.pack('<4sII',b'PYT1',vertex_count,len(indices))
binary+=np.array(packed,dtype='<f4').tobytes()+np.array(indices,dtype='<u2').tobytes()
(OUT/'python.mesh').write_bytes(binary)
(OUT/'manifest.json').write_text(json.dumps({'format':'PYT1','vertices':vertex_count,'triangles':len(indices)//3,'textureSize':2048,'author':'Pytonazz project','license':'Original project asset; no third-party model or texture'},indent=2))
master.hide_render=True;master.hide_viewport=True
bpy.ops.object.select_all(action='DESELECT')
for obj,*_ in records:obj.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(OUT/'python.glb'),use_selection=True,export_format='GLB',export_animations=False)

# Non-destructive presentation copies; production mesh stays in rest position.
presentation=bpy.data.collections.new('Portrait • posed asset');bpy.context.scene.collection.children.link(presentation)
def center(u):
    a=-.55-u*8.9;r=90*(1-.63*u)
    return Vector((math.cos(a)*r,math.sin(a)*r*.63,13+u*11))

for obj,uvs,alongs,material in records:
    posed=obj.copy();posed.data=obj.data.copy();presentation.objects.link(posed)
    for i,vert in enumerate(posed.data.vertices):
        u=alongs[i];c=center(u);d=(center(u+.001)-center(u-.001)).normalized();f=-d
        right=Vector((-f.y,f.x,0)).normalized()
        x,y,z=vert.co
        vert.co=c+f*(0 if material==0 else x)+right*y+Vector((0,0,z))
rest.hide_render=True;rest.hide_viewport=True
world=bpy.context.scene.world;world.use_nodes=True
world.node_tree.nodes['Background'].inputs[0].default_value=(.11,.14,.19,1)
world.node_tree.nodes['Background'].inputs[1].default_value=.35
def area(name,pos,power,size):
    data=bpy.data.lights.new(name,'AREA');data.energy=power;data.shape='DISK';data.size=size
    obj=bpy.data.objects.new(name,data);bpy.context.scene.collection.objects.link(obj);obj.location=pos
    obj.rotation_euler=(Vector((0,0,15))-obj.location).to_track_quat('-Z','Y').to_euler()
area('Key softbox',(30,-110,200),650000,140)
area('Cool rim',(-120,60,100),400000,100)
area('Warm fill',(160,100,70),250000,100)
bpy.ops.object.camera_add(location=(190,-255,235))
camera=bpy.context.object;camera.rotation_euler=(Vector((0,0,15))-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.type='ORTHO';camera.data.ortho_scale=240;bpy.context.scene.camera=camera
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=32
scene.render.resolution_x=1400;scene.render.resolution_y=1100;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG';scene.render.film_transparent=True
scene.view_settings.view_transform='AgX'
scene.render.filepath=str(SOURCE/'python-portrait.png')
bpy.ops.wm.save_as_mainfile(filepath=str(SOURCE/'python.blend'),compress=True)
bpy.ops.render.render(write_still=True)
print('PYTHON_ASSET_COMPLETE',vertex_count,len(indices)//3,flush=True)
