"""Exercises the actual desktop app and Blender process. Writes review artifacts."""
import json
import math
import sys
import time
from pathlib import Path
from PySide6.QtCore import QTimer, Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from studio.app import Studio, ROOT
from studio.transport import request

app=QApplication(sys.argv);window=Studio();window.show();window.start_backend()
started=time.monotonic();phase=0;results={};out=ROOT/'studio_output';out.mkdir(exist_ok=True);benchmark_sequence=0

def call(op,**data):
    reply=request(window.port,window.token,dict(op=op,**data),timeout=30)
    assert reply['ok'],reply
    return reply['result']

def cleanup(code):
    timer.stop()
    if window.process and window.process.poll() is None:
        try:call('shutdown')
        except Exception:window.process.terminate()
        try:window.process.wait(timeout=5)
        except Exception:window.process.terminate()
    if window.network:window.network.running=False;window.network.wait(4000)
    if window.buffer:window.buffer.close();window.buffer=None
    window.ready=False;window.process=None;window.close();app.exit(code)

def step():
    global phase,started,results,benchmark_sequence
    try:
        if phase==0:
            if time.monotonic()-started>100:raise TimeoutError('No preview frame. See blender_bridge.log')
            if window.preview.image.isNull():return
            status=call('status');assert not status['preview_error'],status
            window.preview.image.save(str(out/'smoke_preview.png'));window.grab().save(str(out/'smoke_app.png'))
            results['preview']={'size':[window.preview.image.width(),window.preview.image.height()], 'fps':status['preview_fps']}
            original=status['camera'];initial=status['location'];count=len(status['cameras'])
            moved=call('drive',move=[0,1,0],look=[20,-10],dt=.1,speed=3)
            status=call('status');assert math.dist(initial,status['location'])>.25
            status=call('add_camera',name='Smoke camera');assert len(status['cameras'])==count+1;assert status['camera']!=original
            new=status['camera'];status=call('switch_camera',id=original);assert status['camera']==original
            status=call('switch_camera',id=new);assert status['camera']==new
            status=call('rename_camera',name='Smoke camera renamed');assert any(c['name']=='Smoke camera renamed' for c in status['cameras'])
            status=call('lens',lens=55,dof=True,focus=8,aperture=2,focus_object=None);assert status['lens']==55 and status['dof']
            obj=next(o for o in status['objects'] if o['name']=='Cat body')
            status=call('lens',lens=55,dof=True,focus=8,aperture=2,focus_object=obj['id']);assert status['focus_object']==obj['id']
            call('lens',lens=40,dof=False,focus=8,aperture=2.8,focus_object=None)
            call('timeline',start=1,end=120,fps=24,frame=1,playing=False)
            call('key_camera')
            transform=call('object_state',id=obj['id']);call('object_transform',id=obj['id'],location=transform['location'],rotation=transform['rotation'],scale=transform['scale'],keyframe=True)
            call('timeline',start=1,end=120,fps=24,frame=24,playing=False)
            target=[*transform['location']];target[0]+=.5
            call('object_transform',id=obj['id'],location=target,rotation=transform['rotation'],scale=transform['scale'],keyframe=True)
            call('timeline',start=1,end=120,fps=24,frame=1,playing=False)
            restored=call('object_state',id=obj['id']);assert math.dist(restored['location'],transform['location'])<.001
            call('record',enabled=True);call('drive',move=[1,0,0],look=[0,0],dt=.1,speed=3)
            results['commands']='camera motion, lens, DOF, focus object, duplicate/switch/rename, object keyframes passed'
            results['camera_id']=new;results['object_id']=obj['id'];phase=1;started=time.monotonic()
        elif phase==1:
            if time.monotonic()-started<2:return
            status=call('record',enabled=False);assert status['frame']>1
            results['recorded_to_frame']=status['frame']
            call('timeline',start=1,end=120,fps=24,frame=1,playing=False)
            call('preview',width=480,height=320,fps=15)
            phase=2;started=time.monotonic()
        elif phase==2:
            if window.preview.image.width()!=480:return
            results['quality_switch']='passed'
            benchmark_sequence=window.sequence;started=time.monotonic();phase=3
        elif phase==3:
            if time.monotonic()-started<10:return
            results['steady_eevee_fps']=round((window.sequence-benchmark_sequence)/2/(time.monotonic()-started),2)
            call('preview',width=480,height=320,fps=30,mode='solid',adaptive=False)
            started=time.monotonic();phase=4
        elif phase==4:
            if time.monotonic()-started<2:return
            benchmark_sequence=window.sequence;started=time.monotonic();phase=5
        elif phase==5:
            if time.monotonic()-started<6:return
            results['steady_solid_fps']=round((window.sequence-benchmark_sequence)/2/(time.monotonic()-started),2)
            call('preview',width=720,height=480,fps=15,mode='eevee',adaptive=True)
            started=time.monotonic();phase=6
        elif phase==6:
            if time.monotonic()-started<2 or window.preview.image.width()!=720:return
            benchmark_sequence=window.sequence;started=time.monotonic();phase=7
        elif phase==7:
            if time.monotonic()-started<6:return
            results['steady_720p_eevee_fps']=round((window.sequence-benchmark_sequence)/2/(time.monotonic()-started),2)
            results['before_ui_move']=call('status')['location']
            window.preview.setFocus();QTest.keyPress(window.preview,Qt.Key.Key_W)
            started=time.monotonic();phase=8
        elif phase==8:
            if time.monotonic()-started<1:return
            QTest.keyRelease(window.preview,Qt.Key.Key_W)
            QTest.mousePress(window.preview,Qt.MouseButton.RightButton,pos=QPoint(200,200))
            QTest.mouseMove(window.preview,QPoint(230,210),delay=50)
            QTest.mouseRelease(window.preview,Qt.MouseButton.RightButton,pos=QPoint(230,210))
            window.lens.setValue(45)
            started=time.monotonic();phase=9
        elif phase==9:
            if time.monotonic()-started<1:return
            status=call('status');assert math.dist(status['location'],results.pop('before_ui_move'))>.1
            assert status['lens']==45
            results['ui_controls']='W key, right drag, lens spinbox passed'
            QTest.keyClick(window.preview,Qt.Key.Key_F12)
            path=out/'smoke_saved.blend';window.send('save',path=str(path))
            started=time.monotonic();phase=10
        elif phase==10:
            if time.monotonic()-started<2:return
            assert (out/'smoke_saved.studio.json').exists()
            results['captured_pose']=call('status')
            window.render_still();started=time.monotonic();phase=11
        elif phase==11:
            if time.monotonic()-started>150:raise TimeoutError('High quality render did not finish')
            if window.render_process is None and window.render_output and window.render_output.exists():
                results['high_quality_png']=str(window.render_output)
            else:return
            pose=results.pop('captured_pose');results['captured_camera_location']=pose['location'];results['captured_camera_rotation']=pose['rotation'];results['captured_camera_lens']=pose['lens']
            window.grab().save(str(out/'smoke_app.png'));window.preview.image.save(str(out/'smoke_preview.png'))
            (out/'smoke_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(results,ensure_ascii=False),flush=True);cleanup(0)
    except Exception:
        import traceback;traceback.print_exc();cleanup(1)

timer=QTimer();timer.timeout.connect(step);timer.start(750)
sys.exit(app.exec())
