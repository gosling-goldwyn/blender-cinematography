"""Native Blender aperture, frame settings, and compositor streak effects."""
import math
import bpy
from studio.optics import validate_aspect,output_frame

FLARE_NODE='Forest Studio Anamorphic Flare'

def initialize_formats(scene):
    for cam in scene.objects:
        if cam.type=='CAMERA' and 'fcs_aspect_w' not in cam.data:
            cam.data['fcs_aspect_w']=float(scene.render.resolution_x*scene.render.pixel_aspect_x)
            cam.data['fcs_aspect_h']=float(scene.render.resolution_y*scene.render.pixel_aspect_y)
            cam.data['fcs_output_edge']=max(scene.render.resolution_x,scene.render.resolution_y)

def optics_status(scene,cam):
    return dict(aspect_w=cam.data.get('fcs_aspect_w',scene.render.resolution_x),
                aspect_h=cam.data.get('fcs_aspect_h',scene.render.resolution_y),
                output_edge=cam.data.get('fcs_output_edge',max(scene.render.resolution_x,scene.render.resolution_y)),
                output_width=scene.render.resolution_x,output_height=scene.render.resolution_y,
                blades=cam.data.dof.aperture_blades,bokeh_rotation=math.degrees(cam.data.dof.aperture_rotation),
                bokeh_ratio=cam.data.dof.aperture_ratio,flare=bool(cam.data.get('fcs_flare',False)),
                flare_strength=cam.data.get('fcs_flare_strength',.5),
                flare_threshold=cam.data.get('fcs_flare_threshold',1.0),
                flare_fade=cam.data.get('fcs_flare_fade',.92))

def apply_frame(scene,cam):
    w=cam.data['fcs_aspect_w'];h=cam.data['fcs_aspect_h'];edge=cam.data['fcs_output_edge']
    scene.render.resolution_x,scene.render.resolution_y=output_frame(w,h,edge)
    scene.render.pixel_aspect_x=scene.render.pixel_aspect_y=1
    cam.data.sensor_fit='HORIZONTAL'

def apply_flare(scene,cam):
    enabled=bool(cam.data.get('fcs_flare',False))
    group=scene.compositing_node_group
    node=group.nodes.get(FLARE_NODE) if group else None
    if not enabled and not node:return
    if not group:
        group=bpy.data.node_groups.new('Forest Studio Compositor','CompositorNodeTree')
        group.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
        source=group.nodes.new('CompositorNodeRLayers');source.location=(-400,0)
        output=group.nodes.new('NodeGroupOutput');output.location=(200,0)
        group.links.new(source.outputs['Image'],output.inputs['Image'])
        scene.compositing_node_group=group
    if not node:
        output=next((n for n in group.nodes if n.type=='GROUP_OUTPUT' and n.is_active_output),None)
        if not output:raise ValueError('コンポジターの出力が見つかりません。')
        image=output.inputs.get('Image')
        if image is None or not image.is_linked:raise ValueError('コンポジターのImage出力が接続されていません。')
        source=image.links[0].from_socket
        node=group.nodes.new('CompositorNodeGlare');node.name=FLARE_NODE;node.label='Anamorphic horizontal streaks'
        group.links.new(source,node.inputs['Image']);group.links.new(node.outputs['Image'],image)
        node.location=(output.location.x-180,output.location.y)
    node.mute=not enabled
    node.inputs['Type'].default_value='Streaks';node.inputs['Quality'].default_value='Medium'
    node.inputs['Streaks'].default_value=2;node.inputs['Streaks Angle'].default_value=0
    node.inputs['Threshold'].default_value=float(cam.data.get('fcs_flare_threshold',1))
    node.inputs['Strength'].default_value=float(cam.data.get('fcs_flare_strength',.5))
    node.inputs['Fade'].default_value=float(cam.data.get('fcs_flare_fade',.92))
    node.inputs['Tint'].default_value=(.35,.65,1,1)
    node.inputs['Iterations'].default_value=4

def apply_active_optics(scene):
    apply_frame(scene,scene.camera);apply_flare(scene,scene.camera)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.camera=scene.camera
                area.spaces.active.region_3d.view_perspective='CAMERA'
                area.spaces.active.shading.use_compositor='ALWAYS'

def set_optics(scene,command):
    cam=scene.camera
    w,h=validate_aspect(command['aspect_w'],command['aspect_h'])
    edge=int(command['output_edge']);blades=int(command['blades']);rotation=float(command['bokeh_rotation'])
    ratio=float(command['bokeh_ratio']);strength=float(command['flare_strength']);threshold=float(command['flare_threshold']);fade=float(command['flare_fade'])
    if not (256<=edge<=8192 and (blades==0 or 3<=blades<=16) and -180<=rotation<=180 and .1<=ratio<=10 and 0<=strength<=5 and 0<=threshold<=100 and .5<=fade<=.99):
        raise ValueError('フィルム・ボケ・フレア設定の範囲が不正です。')
    cam.data['fcs_aspect_w']=w;cam.data['fcs_aspect_h']=h;cam.data['fcs_output_edge']=edge
    cam.data.dof.aperture_blades=blades;cam.data.dof.aperture_rotation=math.radians(rotation);cam.data.dof.aperture_ratio=ratio
    cam.data['fcs_flare']=bool(command['flare']);cam.data['fcs_flare_strength']=strength
    cam.data['fcs_flare_threshold']=threshold;cam.data['fcs_flare_fade']=fade
    apply_active_optics(scene)
