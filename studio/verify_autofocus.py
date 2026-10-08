"""Run in Blender after loading an autofocus smoke-test output."""
import json
import sys
from pathlib import Path
import bpy

result=json.loads((Path(__file__).resolve().parent.parent/'studio_output'/'autofocus_results.json').read_text(encoding='utf-8'))
cam=bpy.context.scene.camera
if sys.argv[sys.argv.index('--')+1]=='capture':
    assert cam.data.dof.use_dof
    assert cam.data.dof.focus_object is None
    assert abs(cam.data.dof.focus_distance-result['saved_focus'])<.003
    print('CAPTURE_FOCUS_VERIFIED',cam.data.dof.focus_distance)
else:
    assert cam.data.dof.use_dof
    assert cam.data.dof.focus_object.get('fcs_id')==result['saved_target']
    assert cam.data.get('fcs_focus_target')==result['saved_target']
    bpy.context.scene.frame_set(1);a=cam.data.dof.focus_object.matrix_world.translation.copy()
    bpy.context.scene.frame_set(24);b=cam.data.dof.focus_object.matrix_world.translation.copy()
    assert (b-a).length>2.9
    print('AUTOFOCUS_SAVE_RELOAD_VERIFIED',cam.data.dof.focus_object.name)
