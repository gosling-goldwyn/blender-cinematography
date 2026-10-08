import bpy, math, random, os
from mathutils import Vector

random.seed(28)
ROOT = os.path.dirname(os.path.abspath(__file__))
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

def mat(name, color, rough=0.7, metallic=0):
    m=bpy.data.materials.new(name); m.diffuse_color=(*color,1); m.use_nodes=True
    m.node_tree.nodes.clear()
    p=m.node_tree.nodes.new('ShaderNodeBsdfPrincipled');out=m.node_tree.nodes.new('ShaderNodeOutputMaterial');m.node_tree.links.new(p.outputs['BSDF'],out.inputs['Surface']); p.inputs['Base Color'].default_value=(*color,1)
    p.inputs['Roughness'].default_value=rough; p.inputs['Metallic'].default_value=metallic
    return m
grass=[mat('Meadow '+str(i),c) for i,c in enumerate([(0.19,.30,.075),(.29,.40,.09),(.39,.46,.13),(.12,.24,.09)])]
leaves=[mat('Foliage '+str(i),c) for i,c in enumerate([(.065,.19,.10),(.12,.27,.12),(.23,.34,.12),(.09,.23,.18)])]
bark=mat('Warm bark',(.14,.085,.048)); stone=mat('River stones',(.27,.31,.25))
catmat=mat('Cat charcoal',(.018,.023,.030),.83)
inner=mat('Inner ears',(.10,.065,.075)); eyes=mat('Amber eyes',(.65,.76,.12),.3)
pupil=mat('Pupils',(.005,.009,.01)); nose=mat('Nose',(.065,.055,.06))

def mesh(name,vs,fs,m):
    me=bpy.data.meshes.new(name); me.from_pydata(vs,[],fs); me.update()
    o=bpy.data.objects.new(name,me); bpy.context.collection.objects.link(o); o.data.materials.append(m); return o
def ell(name,loc,scale,m,sub=2):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24,ring_count=16,location=loc)
    o=bpy.context.object; o.name=name; o.scale=scale; o.data.materials.append(m)
    for p in o.data.polygons:p.use_smooth=True
    return o
def branch(name,a,b,r,m,r2=None):
    d=Vector(b)-Vector(a)
    bpy.ops.mesh.primitive_cone_add(vertices=10,radius1=r,radius2=r2 if r2 is not None else r*.65,depth=d.length,location=(Vector(a)+Vector(b))/2)
    o=bpy.context.object;o.name=name;o.rotation_euler=d.to_track_quat('Z','Y').to_euler();o.data.materials.append(m);return o
def curve(name,pts,r,m):
    cu=bpy.data.curves.new(name,'CURVE');cu.dimensions='3D';cu.bevel_depth=r;cu.bevel_resolution=3
    sp=cu.splines.new('BEZIER');sp.bezier_points.add(len(pts)-1)
    for p,co in zip(sp.bezier_points,pts):p.co=co;p.handle_left_type='AUTO';p.handle_right_type='AUTO'
    o=bpy.data.objects.new(name,cu);bpy.context.collection.objects.link(o);o.data.materials.append(m);return o
def center(y):return 1.2+2.0*math.sin(y*.16)
def width(y):return 2.05+0.4*math.sin(y*.21)
def ground(x,y):
    dist=abs(x-center(y))-width(y)
    return .12 + .45*(1-math.exp(-max(0,dist)*.5)) + .12*math.sin(x*.8+y*.4)

# Two banks follow the same meandering river boundary.
for side in [-1,1]:
    vs=[];fs=[]
    for j in range(111):
        y=-12+j*.5
        for i in range(33):
            x=center(y)+side*(width(y)+i*.55)
            vs.append((x,y,ground(x,y)))
    for j in range(110):
        for i in range(32):
            a=j*33+i;fs.append((a,a+1,a+34,a+33))
    o=mesh('Meadow bank '+str(side),vs,fs,grass[0])
    for m in grass[1:]:o.data.materials.append(m)
    for p in o.data.polygons:p.material_index=random.choices(range(4),[7,2,1,2])[0];p.use_smooth=True
water=mat('Deep jade water',(.065,.22,.20),.18,.25)
vs=[];fs=[]
for j in range(111):
    y=-12+j*.5
    for s in [-1,1]:vs.append((center(y)+s*(width(y)+.12),y,.08))
for j in range(110):a=j*2;fs.append((a,a+1,a+3,a+2))
o=mesh('Winding river',vs,fs,water)
nt=water.node_tree;p=next(n for n in nt.nodes if n.type=='BSDF_PRINCIPLED');n=nt.nodes.new('ShaderNodeTexNoise');n.inputs['Scale'].default_value=5;n.inputs['Detail'].default_value=2
tex=nt.nodes.new('ShaderNodeTexCoord');mapping=nt.nodes.new('ShaderNodeVectorMath');mapping.operation='MULTIPLY';mapping.inputs[1].default_value=(1,5,1)
bump=nt.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.22;bump.inputs['Distance'].default_value=.065
nt.links.new(tex.outputs['Generated'],mapping.inputs[0]);nt.links.new(mapping.outputs[0],n.inputs[0]);nt.links.new(n.outputs['Fac'],bump.inputs['Height']);nt.links.new(bump.outputs[0],p.inputs['Normal'])

# Batched grass blades keep the scene light and editable.
gvs=[];gfs=[];gindices=[]
for k in range(13500):
    y=random.uniform(-9,35);side=random.choice([-1,1]);d=random.uniform(.12,12)
    x=center(y)+side*(width(y)+d)
    if (x+2.9)**2+(y+1.0)**2<1.0:continue
    z=ground(x,y);h=random.uniform(.12,.46);w=random.uniform(.025,.07)
    angle=random.random()*math.tau;dx=math.cos(angle)*w;dy=math.sin(angle)*w
    a=len(gvs);gvs.extend([(x-dx,y-dy,z),(x+dx,y+dy,z),(x+random.uniform(-.12,.12),y+random.uniform(-.12,.12),z+h)])
    gfs.append((a,a+1,a+2));gindices.append(random.randrange(4))
o=mesh('Thousands of meadow blades',gvs,gfs,grass[0])
for m in grass[1:]:o.data.materials.append(m)
for p,i in zip(o.data.polygons,gindices):p.material_index=i

for i in range(110):
    y=random.uniform(-5,38);side=random.choice([-1,1]);x=center(y)+side*(width(y)+random.uniform(8.0 if y<7 else 4.0,16))
    z=ground(x,y);h=random.uniform(5,10);r=random.uniform(.14,.32)
    branch('Tree trunk %03d'%i,(x,y,z),(x+.25,y,z+h),r,bark,r*.45)
    for j in range(3):
        ang=random.random()*math.tau;reach=random.uniform(1.2,2.5)
        end=(x+math.cos(ang)*reach,y+math.sin(ang)*reach,z+h-random.uniform(.0,1.2))
        branch('Tree limb',(x,y,z+h*.65),end,r*.5,bark,r*.15)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1,location=end)
        o=bpy.context.object;o.name='Soft angular canopy';o.scale=(random.uniform(1.5,2.2),random.uniform(1.5,2.2),random.uniform(1.2,1.7));o.data.materials.append(random.choice(leaves))

for i in range(95):
    y=random.uniform(-7,32);side=random.choice([-1,1]);x=center(y)+side*(width(y)+random.uniform(-.15,.55))
    o=ell('Bank pebble',(x,y,ground(x,y)-.08),(random.uniform(.12,.5),random.uniform(.13,.45),random.uniform(.10,.25)),stone)

# Cat, assembled from smooth editable meshes, looking towards the camera and water.
cx,cy=-2.9,-1.0;cz=ground(cx,cy)
def C(x,y,z):return (cx+x,cy+y,cz+z)
ell('Cat body',C(0,0,1.02),(.36,.63,.55),catmat)
ell('Cat shoulders',C(0,-.35,1.30),(.32,.32,.48),catmat)
for x in [-.23,.23]:
    ell('Cat front leg',C(x,-.40,.52),(.11,.12,.53),catmat)
    ell('Cat front paw',C(x,-.48,.12),(.14,.20,.12),catmat)
    ell('Cat hind haunch',C(x,.36,.70),(.22,.28,.35),catmat)
    ell('Cat hind leg',C(x,.44,.34),(.12,.13,.30),catmat)
    ell('Cat hind paw',C(x,.32,.11),(.15,.22,.11),catmat)
ell('Cat head',C(0,-.46,1.92),(.42,.34,.39),catmat)
ell('Cat muzzle left',C(-.105,-.75,1.80),(.14,.105,.105),catmat)
ell('Cat muzzle right',C(.105,-.75,1.80),(.14,.105,.105),catmat)
for s in [-1,1]:
    vs=[C(s*.12,-.63,2.13),C(s*.39,-.54,2.08),C(s*.33,-.44,2.65),C(s*.18,-.29,2.10)]
    mesh('Cat pointed ear',vs,[(0,1,2),(1,3,2),(3,0,2),(0,3,1)],catmat)
    mesh('Cat inner ear',[C(s*.17,-.636,2.17),C(s*.34,-.556,2.15),C(s*.315,-.475,2.52)],[(0,1,2)],inner)
    eye=ell('Cat golden eye',C(s*.205,-.746,1.98),(.125,.035,.112),eyes)
    ell('Cat vertical pupil',C(s*.205,-.778,1.98),(.024,.012,.08),pupil)
    glint=mat('Eye glint '+str(s),(1,.95,.74),.1)
    ell('Eye sparkle',C(s*.205-.025,-.791,2.015),(.018,.009,.018),glint)
mesh('Cat nose',[C(-.053,-.852,1.84),C(.053,-.852,1.84),C(0,-.865,1.79)],[(0,1,2)],nose)
curve('Cat raised curved tail',[C(0,.52,.95),C(.13,.88,1.35),C(.18,1.07,1.95),C(.40,1.10,2.29),C(.62,.99,2.20)],.075,catmat)

# A few tiny cream meadow flowers.
flower=mat('Cream wildflowers',(.85,.77,.41))
for i in range(100):
    x=random.uniform(-7,-3.6);y=random.uniform(-5,5);z=ground(x,y)
    branch('Flower stem',(x,y,z),(x,y,z+.3),.012,grass[3])
    ell('Wildflower',(x,y,z+.31),(.065,.065,.045),flower)

scene=bpy.context.scene
scene.render.engine='CYCLES';scene.cycles.samples=48;scene.cycles.use_denoising=True
scene.render.resolution_x=1440;scene.render.resolution_y=960;scene.render.resolution_percentage=75
world=bpy.data.worlds.new('Blue morning');scene.world=world;world.use_nodes=True
world.node_tree.nodes.clear();bg=world.node_tree.nodes.new('ShaderNodeBackground');wo=world.node_tree.nodes.new('ShaderNodeOutputWorld');world.node_tree.links.new(bg.outputs[0],wo.inputs['Surface'])
bg.inputs[0].default_value=(.32,.46,.55,1);bg.inputs[1].default_value=.38
bpy.ops.object.light_add(type='SUN',location=(0,0,10));o=bpy.context.object;o.name='Warm morning sun';o.rotation_euler=(math.radians(25),math.radians(-30),math.radians(-35));o.data.energy=2.2;o.data.angle=.14;o.data.color=(1,.82,.60)
bpy.ops.object.light_add(type='AREA',location=(-3,-4,7));o=bpy.context.object;o.name='Soft sky fill';o.data.energy=550;o.data.shape='DISK';o.data.size=7;o.rotation_euler=(Vector(C(0,0,1))-o.location).to_track_quat('-Z','Y').to_euler()
# Thin atmosphere adds distance without hiding the cat.
fog=bpy.data.materials.new('Morning haze');fog.use_nodes=True;nt=fog.node_tree;nt.nodes.clear()
out=nt.nodes.new('ShaderNodeOutputMaterial');v=nt.nodes.new('ShaderNodeVolumePrincipled');v.inputs['Density'].default_value=.007;v.inputs['Color'].default_value=(.63,.76,.72,1);v.inputs['Anisotropy'].default_value=.25;nt.links.new(v.outputs['Volume'],out.inputs['Volume'])
bpy.ops.mesh.primitive_cube_add(size=1,location=(0,15,8));o=bpy.context.object;o.name='Gentle forest atmosphere';o.scale=(65,65,22);o.data.materials.append(fog);o.display_type='WIRE'
bpy.ops.object.camera_add(location=(-8.8,-13.8,5.8));cam=bpy.context.object;cam.name='River and cat camera';target=Vector((.1,6,1.5));cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.lens=40;scene.camera=cam
scene.view_settings.view_transform='AgX'
scene.render.image_settings.file_format='PNG';scene.render.filepath=os.path.join(ROOT,'flow_forest_preview.png')
# Open directly in the camera view.
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':area.spaces.active.region_3d.view_perspective='CAMERA'
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ROOT,'flow_forest.blend'))
bpy.ops.render.render(write_still=True)
print('FLOW_SCENE_COMPLETE',len(scene.objects),scene.render.filepath)
