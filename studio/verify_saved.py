"""Blender-side regression check for saved animation and still-camera snapshots."""
import json
import math
import sys
from pathlib import Path
import bpy

root=Path(__file__).resolve().parent.parent
results=json.loads((root/'studio_output'/'smoke_results.json').read_text(encoding='utf-8'))
mode=sys.argv[sys.argv.index('--')+1]
scene=bpy.context.scene;cam=scene.camera
if mode=='snapshot':
    assert not cam.animation_data
    assert math.dist(cam.matrix_world.translation,results['captured_camera_location'])<.001
    assert math.dist(cam.rotation_euler,results['captured_camera_rotation'])<.001
    assert abs(cam.data.lens-results['captured_camera_lens'])<.001
    print('CAPTURED_CAMERA_POSE_VERIFIED',cam.name,cam.data.lens)
else:
    assert cam.animation_data and cam.animation_data.action
    scene.frame_set(1);a=cam.matrix_world.translation.copy()
    scene.frame_set(results['recorded_to_frame']);b=cam.matrix_world.translation.copy()
    assert (b-a).length>.2
    obj=scene.objects['Cat body'];scene.frame_set(1);x=obj.location.x
    scene.frame_set(24);assert abs(obj.location.x-x-.5)<.001
    print('SAVE_RELOAD_VERIFIED', 'camera_distance=',(b-a).length,'object_distance=',obj.location.x-x)
