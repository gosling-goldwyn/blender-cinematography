"""Small bright-point scene for visually testing optics without altering user assets."""
from pathlib import Path
import bpy
from mathutils import Vector

bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene
world=bpy.data.worlds.new('Dark optics world');world.use_nodes=True;scene.world=world
world.node_tree.nodes.clear();background=world.node_tree.nodes.new('ShaderNodeBackground');output=world.node_tree.nodes.new('ShaderNodeOutputWorld')
background.inputs['Color'].default_value=(.005,.008,.015,1);background.inputs['Strength'].default_value=.1
world.node_tree.links.new(background.outputs[0],output.inputs['Surface'])
emission=bpy.data.materials.new('Bright points');emission.use_nodes=True;emission.node_tree.nodes.clear()
shader=emission.node_tree.nodes.new('ShaderNodeEmission');shader.inputs['Color'].default_value=(.9,.95,1,1);shader.inputs['Strength'].default_value=1000
if 'Weight' in shader.inputs:shader.inputs['Weight'].default_value=1
output=emission.node_tree.nodes.new('ShaderNodeOutputMaterial');emission.node_tree.links.new(shader.outputs[0],output.inputs['Surface'])
for i,(x,z) in enumerate([(-2.2,1.4),(-1.1,.5),(0,1.8),(1.1,.6),(2.2,1.3)]):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8,radius=.04,location=(x,5,z));bpy.context.object.name='Bright dot '+str(i);bpy.context.object.data.materials.append(emission)
bpy.ops.mesh.primitive_cube_add(size=.08,location=(0,-6,1));bpy.context.object.name='Focus target'
bpy.ops.object.light_add(type='AREA',location=(0,-7,4));light=bpy.context.object;light.data.energy=150;light.data.size=4;light.rotation_euler=(Vector((0,-6,1))-light.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=(0,-8,1));cam=bpy.context.object;cam.rotation_euler=(Vector((0,3,1))-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.lens=50;cam.data.dof.use_dof=True;cam.data.dof.focus_distance=2;cam.data.dof.aperture_fstop=.7;scene.camera=cam
scene.render.resolution_x=1280;scene.render.resolution_y=800;scene.render.resolution_percentage=100
scene.render.engine='BLENDER_EEVEE';scene.view_settings.view_transform='AgX'
scene.render.image_settings.file_format='PNG'
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':area.spaces.active.region_3d.view_perspective='CAMERA'
path=Path(__file__).resolve().parent.parent/'studio_output'/'optics_fixture.blend';path.parent.mkdir(exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(path));print('OPTICS_FIXTURE_READY')
