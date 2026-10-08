"""Background Cycles still renderer, isolated from interactive preview."""
import argparse
import sys
from pathlib import Path
import bpy

parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
parser.add_argument('--width',type=int);parser.add_argument('--height',type=int)
parser.add_argument('--samples',type=int,default=48)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=args.samples
scene.cycles.use_denoising=True;scene.render.resolution_percentage=100
if args.width:scene.render.resolution_x=args.width
if args.height:scene.render.resolution_y=args.height
try:
    prefs=bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type='CUDA';prefs.get_devices()
    available=[d for d in prefs.devices if d.type=='CUDA']
    if available:
        for device in prefs.devices:device.use=device.type=='CUDA'
        scene.cycles.device='GPU'
except Exception as exc:print('GPU setup unavailable; using CPU:',str(exc))
scene.render.image_settings.file_format='PNG';scene.render.filepath=str(Path(args.output).resolve())
bpy.ops.render.render(write_still=True)
print('FOREST_STUDIO_RENDER_COMPLETE',scene.render.filepath,flush=True)
