"""Actual Qt/Blender integration check for object autofocus and saved focus settings."""
import json
import sys
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from studio.app import ROOT, Studio
from studio.transport import request

app=QApplication(sys.argv);window=Studio();window.show();window.start_backend()
out=ROOT/'studio_output';phase=0;started=time.monotonic();results={}

def call(op,**data):
    reply=request(window.port,window.token,dict(op=op,**data),timeout=30)
    assert reply['ok'],reply
    return reply['result']

def finish(code):
    timer.stop()
    if window.process and window.process.poll() is None:
        try:call('shutdown');window.process.wait(timeout=5)
        except Exception:window.process.terminate()
    if window.network:window.network.running=False;window.network.wait(4000)
    if window.buffer:window.buffer.close();window.buffer=None
    window.ready=False;window.process=None;window.close();app.exit(code)

def step():
    global phase,started,results
    try:
        if phase==0:
            if time.monotonic()-started>90:raise TimeoutError('No initial preview')
            if not window.ready or window.preview.image.isNull():return
            status=call('status');target=next(o for o in status['objects'] if o['name']=='Cat body')
            results['target']=target['id'];results['camera']=status['camera']
            window.object_list.setCurrentIndex(window.object_list.findData(target['id']))
            window.focus_selected_object();started=time.monotonic();phase=1
        elif phase==1:
            if time.monotonic()-started<1:return
            status=call('status');assert status['autofocus'] and status['dof'] and status['focus_object']==results['target']
            assert window.autofocus.isChecked() and not window.focus.isEnabled()
            results['initial_focus']=status['focus']
            call('drive',move=[0,1,0],look=[0,0],dt=.1,speed=3)
            moved=call('status');assert abs(moved['focus']-results['initial_focus']+.3)<.003
            results['camera_move_focus']=moved['focus']
            transform=call('object_state',id=results['target']);results['transform']=transform
            call('timeline',start=1,end=60,fps=24,frame=1,playing=False)
            call('object_transform',id=results['target'],location=transform['location'],rotation=transform['rotation'],scale=transform['scale'],keyframe=True)
            location=list(transform['location']);location[1]+=3
            call('timeline',start=1,end=60,fps=24,frame=24,playing=False)
            call('object_transform',id=results['target'],location=location,rotation=transform['rotation'],scale=transform['scale'],keyframe=True)
            at24=call('status');call('timeline',start=1,end=60,fps=24,frame=1,playing=False);at1=call('status')
            assert at24['focus']>at1['focus']+1
            results['animated_focus']=[at1['focus'],at24['focus']]
            call('add_camera',name='AF second camera')
            second=call('status');assert second['autofocus'] and second['focus_object']==results['target']
            call('lens',lens=50,dof=True,focus=8,aperture=2.8,focus_object=None,autofocus=False)
            call('switch_camera',id=results['camera']);assert call('status')['autofocus']
            results['per_camera']='passed'
            window.autofocus.setChecked(False);started=time.monotonic();phase=2
        elif phase==2:
            if time.monotonic()-started<1:return
            status=call('status');assert not status['autofocus'] and status['focus_target']==results['target']
            assert abs(status['focus']-results['animated_focus'][0])<.003
            manual=status['focus'];call('drive',move=[0,1,0],look=[0,0],dt=.1,speed=3)
            assert abs(call('status')['focus']-manual)<.003
            results['manual_hold']='passed'
            window.autofocus.setChecked(True);started=time.monotonic();phase=3
        elif phase==3:
            if time.monotonic()-started<1:return
            status=call('status');assert status['autofocus'] and status['dof']
            results['saved_focus']=status['focus'];results['saved_target']=status['focus_object']
            call('save',path=str(out/'autofocus_saved.blend'))
            call('render_snapshot',path=str(out/'autofocus_capture.blend'))
            window.grab().save(str(out/'autofocus_app.png'))
            results.pop('transform');(out/'autofocus_results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
            print(json.dumps(results),flush=True);finish(0)
    except Exception:
        import traceback;traceback.print_exc();finish(1)

timer=QTimer();timer.timeout.connect(step);timer.start(500)
sys.exit(app.exec())
