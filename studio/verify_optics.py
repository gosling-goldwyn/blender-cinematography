"""Blender-side optics save/reload and compositor-chain regression verification."""
import sys
import math
import json
import struct
from pathlib import Path
import bpy

root=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(root))
from studio.blender_optics import FLARE_NODE,apply_flare
result=json.loads((root/'studio_output'/'optics_results.json').read_text(encoding='utf-8'))
scene=bpy.context.scene;cam=scene.camera
assert (scene.render.resolution_x,scene.render.resolution_y)==(640,268)
assert abs(cam.data['fcs_aspect_w']/cam.data['fcs_aspect_h']-2.39)<.00001
assert cam.data.sensor_fit=='HORIZONTAL'
assert cam.data.dof.aperture_blades==0 and cam.data.dof.aperture_ratio==2
assert abs(math.degrees(cam.data.dof.aperture_rotation)-20)<.001
node=scene.compositing_node_group.nodes[FLARE_NODE]
assert not node.mute and node.inputs['Streaks'].default_value==2
assert abs(node.inputs['Strength'].default_value-1.5)<.001
with open(result['high_quality_png'],'rb') as image:
    header=image.read(24);assert header[:8]==b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II',header[16:24])==(640,268)
print('OPTICS_SAVE_RELOAD_AND_PNG_SIZE_VERIFIED')

# An existing user graph must remain connected when adding/disabling streaks.
group=bpy.data.node_groups.new('Existing graph test','CompositorNodeTree')
group.interface.new_socket(name='Image',in_out='OUTPUT',socket_type='NodeSocketColor')
source=group.nodes.new('CompositorNodeRLayers');balance=group.nodes.new('CompositorNodeBrightContrast');output=group.nodes.new('NodeGroupOutput')
group.links.new(source.outputs['Image'],balance.inputs['Image']);group.links.new(balance.outputs['Image'],output.inputs['Image'])
scene.compositing_node_group=group;apply_flare(scene,cam)
glare=group.nodes[FLARE_NODE]
assert glare.inputs['Image'].links[0].from_node==balance
assert output.inputs['Image'].links[0].from_node==glare
cam.data['fcs_flare']=False;apply_flare(scene,cam)
assert glare.mute and balance.inputs['Image'].links[0].from_node==source
print('EXISTING_COMPOSITOR_PRESERVED')
