"""Runs in Blender's GUI process. All bpy/GPU work stays on the main thread."""
import argparse
import json
import math
import os
import queue
import socket
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import bpy
import gpu
from mathutils import Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio.transport import HEADER, OFFSET, open_buffer, MAX_WIDTH, MAX_HEIGHT

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, required=True)
parser.add_argument('--token', required=True)
parser.add_argument('--buffer', required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
commands = queue.Queue()
frame_buffer = open_buffer(args.buffer)
state = dict(width=720, height=480, fps=15, playing=False, recording=False,
             frame=1.0, last_tick=time.perf_counter(), last_draw=0.0, sequence=0,
             offscreen=None, draw_busy=False, error='', stopping=False,
             drawn=0, measured_fps=0.0, fps_time=time.perf_counter(), dirty=True,
             mode='eevee', adaptive=True, last_move=0.0)


def object_id(obj):
    if 'fcs_id' not in obj:
        obj['fcs_id'] = uuid.uuid4().hex
    return obj['fcs_id']


def find_object(identifier):
    for obj in bpy.context.scene.objects:
        if obj.get('fcs_id') == identifier:
            return obj
    raise ValueError('Object no longer exists')


def camera():
    cam = bpy.context.scene.camera
    if not cam:
        raise ValueError('No active camera')
    return cam


def focus_distance(cam):
    """Report the focus-plane distance used by Blender, including animation/parents."""
    target=cam.data.dof.focus_object
    if not target:return cam.data.dof.focus_distance
    deps=bpy.context.evaluated_depsgraph_get()
    evaluated=cam.evaluated_get(deps);target=target.evaluated_get(deps)
    point=target.matrix_world.translation
    bone=target.pose.bones.get(cam.data.dof.focus_subtarget) if target.type=='ARMATURE' and target.pose else None
    if bone:point=(target.matrix_world @ bone.matrix).translation
    axis=evaluated.matrix_world.col[2].to_3d().normalized()
    return max(.00001,abs((evaluated.matrix_world.translation-point).dot(axis)))


def snapshot():
    scene = bpy.context.scene
    cam = camera()
    active_target=cam.data.dof.focus_object
    target_id=object_id(active_target) if active_target else cam.data.get('fcs_focus_target') or None
    if target_id and not any(o.get('fcs_id')==target_id for o in scene.objects):target_id=None
    return dict(camera=object_id(cam), cameras=[dict(id=object_id(o), name=o.name)
                for o in scene.objects if o.type == 'CAMERA'],
                objects=[dict(id=object_id(o), name=o.name, type=o.type)
                         for o in scene.objects if o.type in {'MESH', 'EMPTY', 'ARMATURE'}],
                lens=cam.data.lens, dof=cam.data.dof.use_dof,
                focus=focus_distance(cam), aperture=cam.data.dof.aperture_fstop,
                focus_object=object_id(active_target) if active_target else None,
                focus_target=target_id, autofocus=active_target is not None,
                frame=scene.frame_current, start=scene.frame_start, end=scene.frame_end,
                fps=scene.render.fps / scene.render.fps_base, playing=state['playing'],
                recording=state['recording'], preview_fps=round(state['measured_fps'], 1),
                preview_error=state['error'], width=state['width'], height=state['height'],
                location=list(cam.location), rotation=list(cam.rotation_euler),
                source=bpy.data.filepath, mode=state['mode'], adaptive=state['adaptive'])


def key_camera(cam):
    cam.keyframe_insert(data_path='location', group='Camera movement')
    path='rotation_quaternion' if cam.rotation_mode=='QUATERNION' else 'rotation_axis_angle' if cam.rotation_mode=='AXIS_ANGLE' else 'rotation_euler'
    cam.keyframe_insert(data_path=path, group='Camera movement')
    cam.data.keyframe_insert(data_path='lens', group='Lens')
    cam.data.dof.keyframe_insert(data_path='focus_distance', group='Lens')
    cam.data.dof.keyframe_insert(data_path='aperture_fstop', group='Lens')


def configure_view():
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_samples=2
    scene.eevee.volumetric_samples=16
    scene.eevee.volumetric_tile_size='16'
    scene.eevee.use_fast_gi=False
    # The working copy uses EEVEE. Source files are never overwritten implicitly.
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                space.shading.type = 'RENDERED'
                space.shading.use_scene_world_render = True
                space.shading.use_scene_lights_render = True
                space.overlay.show_overlays = False
                space.region_3d.view_perspective = 'CAMERA'
    if not scene.camera:
        data = bpy.data.cameras.new('Studio Camera')
        obj = bpy.data.objects.new('Studio Camera', data)
        scene.collection.objects.link(obj)
        obj.location = (0, -10, 4)
        obj.rotation_euler = (Vector((0, 0, 1))-obj.location).to_track_quat('-Z', 'Y').to_euler()
        scene.camera = obj
    state['frame'] = float(scene.frame_current)


def execute(cmd):
    op = cmd['op']; scene = bpy.context.scene
    if op == 'status':
        return snapshot()
    if op == 'drive':
        if state['playing'] and not state['recording']:
            return {}
        cam = camera()
        dt = max(0.0, min(float(cmd.get('dt', .04)), .15))
        speed = max(.01, min(float(cmd.get('speed', 3)), 100))
        xyz = cmd.get('move', [0, 0, 0]); look = cmd.get('look', [0, 0])
        q = cam.matrix_basis.to_quaternion()
        q = Quaternion((0, 0, 1), -look[0] * .003) @ q @ Quaternion((1, 0, 0), -look[1] * .003)
        if cam.rotation_mode=='QUATERNION':cam.rotation_quaternion=q
        elif cam.rotation_mode=='AXIS_ANGLE':
            axis,angle=q.to_axis_angle();cam.rotation_axis_angle=(angle,*axis)
        else:cam.rotation_euler=q.to_euler(cam.rotation_mode)
        direction = q @ Vector((xyz[0], 0, -xyz[1])) + Vector((0, 0, xyz[2]))
        if direction.length > 1: direction.normalize()
        cam.location += direction * dt * speed
        state['last_move']=time.perf_counter()
        state['dirty'] = True
        return {}
    if op == 'lens':
        cam = camera()
        target=find_object(cmd['focus_object']) if cmd.get('focus_object') else None
        autofocus=bool(cmd.get('autofocus',target is not None))
        if autofocus and target is None:raise ValueError('オートフォーカスの対象を選んでください。')
        previous_distance=focus_distance(cam)
        was_auto=cam.data.dof.focus_object is not None
        cam.data.lens = max(8, min(300, float(cmd['lens'])))
        cam.data.dof.use_dof = bool(cmd['dof'])
        cam.data.dof.focus_distance = max(.00001,previous_distance if was_auto and not autofocus else float(cmd['focus']))
        cam.data.dof.aperture_fstop = max(.1, min(128, float(cmd['aperture'])))
        cam.data.dof.focus_object = target if autofocus else None
        cam.data.dof.focus_subtarget=''
        cam.data['fcs_focus_target']=object_id(target) if target else ''
        state['dirty'] = True
        return snapshot()
    if op == 'switch_camera':
        if state['recording']: raise ValueError('Stop recording before switching camera')
        obj = find_object(cmd['id'])
        if obj.type != 'CAMERA': raise ValueError('Selected object is not a camera')
        scene.camera = obj
        state['dirty'] = True
        return snapshot()
    if op == 'add_camera':
        if state['recording']: raise ValueError('Stop recording before adding camera')
        original = camera(); new = original.copy(); new.data = original.data.copy()
        new.animation_data_clear(); new.data.animation_data_clear()
        new['fcs_id'] = uuid.uuid4().hex
        new.name = cmd.get('name', 'Camera')
        scene.collection.objects.link(new); scene.camera = new
        state['dirty'] = True
        return snapshot()
    if op == 'rename_camera':
        camera().name = cmd['name'].strip() or 'Camera'
        return snapshot()
    if op == 'preview':
        w,h = int(cmd['width']),int(cmd['height'])
        if not (160 <= w <= MAX_WIDTH and 120 <= h <= MAX_HEIGHT): raise ValueError('Invalid preview dimensions')
        mode=cmd.get('mode','eevee')
        if mode not in {'eevee','solid'}:raise ValueError('Unknown preview mode')
        state.update(width=w, height=h, fps=max(1,min(30,int(cmd.get('fps',15)))), dirty=True, mode=mode, adaptive=bool(cmd.get('adaptive',True)))
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type=='VIEW_3D':
                    space=area.spaces.active
                    space.shading.type='RENDERED' if mode=='eevee' else 'SOLID'
                    if mode=='solid':space.shading.color_type='MATERIAL'
        return snapshot()
    if op == 'timeline':
        if state['recording']: raise ValueError('Stop recording before changing timeline')
        start, end = int(cmd['start']), int(cmd['end'])
        if end < start: raise ValueError('End frame must not precede start')
        scene.frame_start=start; scene.frame_end=end
        scene.render.fps=max(1,min(120,int(cmd['fps']))); scene.render.fps_base=1
        frame=max(start,min(end,int(cmd['frame'])));scene.frame_set(frame);state['frame']=float(frame)
        state['playing']=bool(cmd.get('playing',False));state['dirty']=True
        return snapshot()
    if op == 'key_camera':
        key_camera(camera());return snapshot()
    if op == 'record':
        state['recording']=bool(cmd['enabled']);state['playing']=state['recording'];state['frame']=float(scene.frame_current)
        if state['recording']: key_camera(camera())
        return snapshot()
    if op == 'object_state':
        obj=find_object(cmd['id'])
        return dict(id=object_id(obj), location=list(obj.location), rotation=[math.degrees(v) for v in obj.rotation_euler], scale=list(obj.scale))
    if op == 'object_transform':
        obj=find_object(cmd['id'])
        obj.location=cmd['location'];obj.rotation_euler=[math.radians(v) for v in cmd['rotation']];obj.scale=cmd['scale']
        if cmd.get('keyframe'):
            for path in ('location','rotation_euler','scale'): obj.keyframe_insert(data_path=path, group='Object transform')
        state['dirty']=True
        return {}
    if op == 'save':
        path=str(Path(cmd['path']).resolve())
        bpy.ops.wm.save_as_mainfile(filepath=path)
        return dict(path=path)
    if op == 'render_snapshot':
        path=str(Path(cmd['path']).resolve())
        original=camera();deps=bpy.context.evaluated_depsgraph_get();evaluated=original.evaluated_get(deps)
        captured_matrix=evaluated.matrix_world.copy()
        captured_focus=focus_distance(original)
        captured=original.copy();captured.data=evaluated.data.copy()
        captured.animation_data_clear();captured.data.animation_data_clear()
        captured.data.dof.focus_distance=captured_focus;captured.data.dof.focus_object=None
        captured.constraints.clear();captured.parent=None;captured.name='Captured camera'
        captured['fcs_id']=uuid.uuid4().hex
        scene.collection.objects.link(captured);captured.matrix_world=captured_matrix
        scene.camera=captured
        try:
            bpy.context.view_layer.update()
            bpy.ops.wm.save_as_mainfile(filepath=path,copy=True)
        finally:
            scene.camera=original;data=captured.data
            bpy.data.objects.remove(captured,do_unlink=True);bpy.data.cameras.remove(data)
        return dict(path=path)
    if op == 'shutdown':
        state['stopping']=True
        return {}
    raise ValueError('Unknown operation: '+op)


def serve():
    with socket.socket() as server:
        server.bind(('127.0.0.1', args.port));server.listen(8);server.settimeout(.5)
        while not state['stopping']:
            try: conn,_ = server.accept()
            except socket.timeout: continue
            with conn:
                try:
                    conn.settimeout(5);raw=bytearray()
                    while b'\n' not in raw:
                        chunk=conn.recv(4096)
                        if not chunk: raise ValueError('Empty request')
                        raw.extend(chunk)
                        if len(raw)>1024*1024:raise ValueError('Request too large')
                    cmd=json.loads(bytes(raw).split(b'\n',1)[0])
                    if cmd.pop('token',None) != args.token:raise ValueError('Invalid session token')
                    reply=queue.Queue(maxsize=1);commands.put((cmd,reply))
                    response=reply.get(timeout=60)
                except Exception as exc:response=dict(ok=False,error=str(exc))
                try:conn.sendall(json.dumps(response,ensure_ascii=False).encode('utf-8')+b'\n')
                except OSError:pass


def draw():
    if state['draw_busy'] or state['stopping']:return
    area=bpy.context.area
    if not area or area.type!='VIEW_3D':return
    now=time.perf_counter()
    if now-state['last_draw'] < 1/state['fps']:return
    state['draw_busy']=True
    try:
        w,h=state['width'],state['height']
        if state['adaptive'] and now-state['last_move']<.3:
            w=max(160,int(w*.67));h=max(120,int(h*.67))
        off=state['offscreen']
        if off is None or off.width!=w or off.height!=h:
            if off:off.free()
            off=gpu.types.GPUOffScreen(w,h);state['offscreen']=off
        cam=camera();deps=bpy.context.evaluated_depsgraph_get();evaluated=cam.evaluated_get(deps)
        projection=evaluated.calc_matrix_camera(deps,x=w,y=h,scale_x=1,scale_y=1)
        off.draw_view3d(bpy.context.scene,bpy.context.view_layer,area.spaces.active,
                       bpy.context.region,evaluated.matrix_world.inverted(),projection,
                       do_color_management=True,draw_background=True)
        with off.bind():
            pixels=gpu.state.active_framebuffer_get().read_color(0,0,w,h,4,0,'UBYTE')
        raw=memoryview(pixels).tobytes()
        seq=state['sequence']+2;stamp=time.time_ns()
        frame_buffer[:HEADER.size]=HEADER.pack(b'FCS1',w,h,len(raw),seq-1,stamp)
        frame_buffer[OFFSET:OFFSET+len(raw)]=raw
        frame_buffer[:HEADER.size]=HEADER.pack(b'FCS1',w,h,len(raw),seq,stamp)
        state['sequence']=seq;state['last_draw']=now;state['error']='';state['drawn']+=1
        if now-state['fps_time']>=2:
            state['measured_fps']=state['drawn']/(now-state['fps_time']);state['drawn']=0;state['fps_time']=now
    except Exception as exc:
        if state['error']!=str(exc):traceback.print_exc()
        state['error']=str(exc);state['last_draw']=now
    finally:state['draw_busy']=False


def tick():
    now=time.perf_counter();dt=min(now-state['last_tick'],1.0);state['last_tick']=now
    for _ in range(32):
        try:cmd,reply=commands.get_nowait()
        except queue.Empty:break
        try:reply.put(dict(ok=True,result=execute(cmd)))
        except Exception as exc:reply.put(dict(ok=False,error=str(exc)))
    if state['playing']:
        scene=bpy.context.scene;state['frame']+=dt*scene.render.fps/scene.render.fps_base
        if state['frame']>scene.frame_end:
            if state['recording']:state['recording']=False;state['playing']=False;state['frame']=float(scene.frame_end)
            else:state['frame']=float(scene.frame_start)
        if state['recording']:
            cam=camera();pose=(cam.location.copy(),cam.rotation_euler.copy(),cam.rotation_quaternion.copy(),tuple(cam.rotation_axis_angle),cam.data.lens,cam.data.dof.focus_distance,cam.data.dof.aperture_fstop)
        frame=int(state['frame']);scene.frame_set(frame,subframe=state['frame']-frame)
        if state['recording']:
            cam.location=pose[0];cam.rotation_euler=pose[1];cam.rotation_quaternion=pose[2];cam.rotation_axis_angle=pose[3];cam.data.lens=pose[4];cam.data.dof.focus_distance=pose[5];cam.data.dof.aperture_fstop=pose[6]
            key_camera(cam)
    for area in bpy.context.screen.areas:
        if area.type=='VIEW_3D':area.tag_redraw()
    if state['stopping']:
        bpy.types.SpaceView3D.draw_handler_remove(draw_handle,'WINDOW')
        if state['offscreen']:
            state['offscreen'].free();state['offscreen']=None
        frame_buffer.close()
        bpy.ops.wm.quit_blender();return None
    return .02


configure_view()
draw_handle=bpy.types.SpaceView3D.draw_handler_add(draw,(), 'WINDOW','POST_PIXEL')
bpy.app.timers.register(tick,first_interval=.1,persistent=True)
threading.Thread(target=serve,daemon=True).start()
print('FOREST_STUDIO_BRIDGE_READY',args.port,flush=True)
