"""Live camera format / aperture / viewport compositor / Cycles integration test."""
import json
import sys
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from studio.app import Studio,ROOT
from studio.optics import ASPECTS,fit_frame,output_frame
from studio.transport import request

app=QApplication(sys.argv);window=Studio();window.scene_path=ROOT/'studio_output'/'optics_fixture.blend'
errors=[]
window.on_error=lambda op,message: errors.append((op,message)) if op!='status' else None
window.show();window.start_backend();out=ROOT/'studio_output';phase=0;started=time.monotonic();results={}

def call(op,**data):
    reply=request(window.port,window.token,dict(op=op,**data),timeout=30)
    assert reply['ok'],reply
    return reply['result']

def payload(status,**changes):
    data={k:status[k] for k in ('aspect_w','aspect_h','output_edge','blades','bokeh_rotation','bokeh_ratio','flare','flare_strength','flare_threshold','flare_fade')}
    return dict(data,**changes)

def settle():
    return time.monotonic()-started>=2 and not window.preview.image.isNull()

def capture(name):
    image=window.preview.image;image.save(str(out/(name+'.png')))
    return image.copy()

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
        if errors:raise AssertionError(errors)
        if phase==0:
            if time.monotonic()-started>60:raise TimeoutError('No optics preview')
            if not window.ready or window.preview.image.isNull():return
            status=call('status');original=status['camera'];results['original_camera']=original
            checked=[]
            for name,w,h in ASPECTS:
                status=call('optics',**payload(status,aspect_w=w,aspect_h=h))
                assert (status['output_width'],status['output_height'])==output_frame(w,h,status['output_edge'])
                checked.append(name)
            results['formats']=checked
            window.aspect.setCurrentIndex(8);window.output_edge.setValue(640);window.bokeh_shape.setCurrentIndex(0);window.choose_bokeh()
            window.quality.setCurrentIndex(1);window.adaptive.setChecked(False)
            started=time.monotonic();phase=1
        elif phase==1:
            if not settle() or window.preview.image.width()!=720 or window.preview.image.height()!=301:return
            status=call('status');assert status['blades']==0 and abs(status['aspect_w']/status['aspect_h']-2.39)<.001
            results['preview_size']=[window.preview.image.width(),window.preview.image.height()]
            results['round_image']=capture('optics_round');window.bokeh_shape.setCurrentIndex(5);window.bokeh_rotation.setValue(20)
            started=time.monotonic();phase=2
        elif phase==2:
            if not settle():return
            status=call('status');assert status['blades']==8 and abs(status['bokeh_rotation']-20)<.001
            polygon=capture('optics_polygon');round_image=results['round_image']
            assert sum(abs(a-b) for a,b in zip(bytes(polygon.constBits()),bytes(round_image.constBits())))>1000
            window.bokeh_shape.setCurrentIndex(6)
            started=time.monotonic();phase=3
        elif phase==3:
            if not settle():return
            status=call('status');assert status['blades']==0 and status['bokeh_ratio']==2
            results['flare_off_image']=capture('optics_anamorphic')
            def extent(image):
                points=[(x,y) for y in range(100,153) for x in range(500,562) if image.pixelColor(x,y).red()>30]
                assert points,'Missing bright bokeh'
                return max(x for x,y in points)-min(x for x,y in points),max(y for x,y in points)-min(y for x,y in points)
            circular=extent(results.pop('round_image'));oval=extent(results['flare_off_image'])
            assert oval[1]/max(1,oval[0])>circular[1]/max(1,circular[0])*1.4,(circular,oval)
            results['bokeh_extents']={'round':circular,'anamorphic':oval}
            window.flare_strength.setValue(1.5);window.flare_threshold.setValue(.5);window.flare.setChecked(True)
            started=time.monotonic();phase=4
        elif phase==4:
            if not settle():return
            status=call('status');assert status['flare'] and not status['preview_error']
            image=capture('optics_flare');before=results.pop('flare_off_image')
            # Glare must change actual pixels, rather than merely save its toggle.
            a=bytes(before.constBits());b=bytes(image.constBits())
            difference=sum(abs(x-y) for x,y in zip(a,b))/len(a)
            # A blue horizontal streak must brighten a dark area away from the point itself.
            before_blue=before.pixelColor(320,89).blue();after_blue=image.pixelColor(320,89).blue()
            assert after_blue>before_blue+5,('Viewport flare absent',before_blue,after_blue,difference)
            results['flare_pixel_difference']=difference
            second=call('add_camera',name='Second optics camera')
            call('optics',**payload(second,aspect_w=2,aspect_h=3,blades=3,bokeh_ratio=1,flare=False))
            call('switch_camera',id=results['original_camera']);status=call('status')
            assert status['flare'] and status['blades']==0 and status['bokeh_ratio']==2
            results['camera_switch']='passed'
            call('save',path=str(out/'optics_saved.blend'))
            window.render_still();started=time.monotonic();phase=5
        elif phase==5:
            if time.monotonic()-started>90:raise TimeoutError('Optics still render timeout')
            if window.render_process or not window.render_output or not window.render_output.exists():return
            results['high_quality_png']=str(window.render_output)
            window.tabs.setCurrentIndex(1)
            window.grab().save(str(out/'optics_app.png'))
            (out/'optics_results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
            print(json.dumps(results),flush=True);finish(0)
    except Exception:
        import traceback;traceback.print_exc();finish(1)

timer=QTimer();timer.timeout.connect(step);timer.start(500)
sys.exit(app.exec())
