import json
import os
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QFormLayout,
    QGroupBox, QDockWidget, QFileDialog, QMessageBox, QInputDialog, QSlider, QTabWidget)

from studio.transport import open_buffer, read_frame, request

ROOT=Path(__file__).resolve().parent.parent
DEFAULT_BLENDER=Path(r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe')


class Network(QThread):
    response=Signal(str,object)
    failed=Signal(str,str)

    def __init__(self,port,token):
        super().__init__();self.port=port;self.token=token;self.commands=queue.Queue()
        self.latest_drive=None;self.running=True;self.status_pending=False
        self.drive_lock=threading.Lock()

    def post(self,op,**data):
        if op=='drive':
            with self.drive_lock:
                if self.latest_drive:
                    data['look']=[a+b for a,b in zip(data['look'],self.latest_drive['look'])]
                    data['dt']=min(.15,data['dt']+self.latest_drive['dt'])
                self.latest_drive=dict(op=op,**data)
            return
        if op=='status':
            if self.status_pending:return
            self.status_pending=True
        self.commands.put(dict(op=op,**data))

    def run(self):
        while self.running:
            try:cmd=self.commands.get(timeout=.025)
            except queue.Empty:
                with self.drive_lock:cmd=self.latest_drive;self.latest_drive=None
                if cmd is None:continue
            op=cmd['op']
            try:
                reply=request(self.port,self.token,cmd,timeout=30 if op in {'save','render_snapshot'} else 3)
                if not reply.get('ok'):raise RuntimeError(reply.get('error','Unknown error'))
                self.response.emit(op,reply['result'])
            except Exception as exc:self.failed.emit(op,str(exc))
            finally:
                if op=='status':self.status_pending=False


class Preview(QWidget):
    camera_shortcut=Signal(int)
    capture_shortcut=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(480,320);self.image=QImage();self.keys=set();self.last_pos=None
        self.look=[0.,0.];self.speed=3.;self.message='シーンを開いてBlenderを起動してください'
        self.setMouseTracking(True)

    def paintEvent(self,event):
        p=QPainter(self);p.fillRect(self.rect(),QColor('#121820'))
        if not self.image.isNull():
            size=self.image.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
            x=(self.width()-size.width())//2;y=(self.height()-size.height())//2
            p.drawImage(x,y,self.image.scaled(size,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        p.fillRect(0,0,self.width(),34,QColor(10,15,20,205));p.setPen(QColor('#e4edf3'))
        p.drawText(12,23,self.message)

    def keyPressEvent(self,event):
        if not event.isAutoRepeat() and Qt.Key.Key_1<=event.key()<=Qt.Key.Key_9:
            self.camera_shortcut.emit(event.key()-Qt.Key.Key_1);event.accept();return
        if event.key()==Qt.Key.Key_F12:
            self.capture_shortcut.emit();event.accept();return
        self.keys.add(event.key());event.accept()

    def keyReleaseEvent(self,event):
        if not event.isAutoRepeat():self.keys.discard(event.key())
        event.accept()

    def focusOutEvent(self,event):
        self.keys.clear();self.last_pos=None;self.unsetCursor();super().focusOutEvent(event)

    def mousePressEvent(self,event):
        self.setFocus()
        if event.button()==Qt.MouseButton.RightButton:
            self.last_pos=event.position();self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self,event):
        if self.last_pos is not None:
            delta=event.position()-self.last_pos;self.look[0]+=delta.x();self.look[1]+=delta.y();self.last_pos=event.position()

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.RightButton:self.last_pos=None;self.unsetCursor()

    def wheelEvent(self,event):
        self.speed=max(.05,min(50,self.speed*1.2**(event.angleDelta().y()/120)))
        event.accept()

    def motion(self,dt):
        K=Qt.Key;k=self.keys
        move=[int(K.Key_D in k)-int(K.Key_A in k),int(K.Key_W in k)-int(K.Key_S in k),int(K.Key_E in k)-int(K.Key_Q in k)]
        look=[self.look[0]+(int(K.Key_Right in k)-int(K.Key_Left in k))*dt*260,
              self.look[1]+(int(K.Key_Down in k)-int(K.Key_Up in k))*dt*260]
        self.look=[0.,0.]
        if any(move) or any(look):return dict(move=move,look=look,dt=dt,speed=self.speed*(3 if K.Key_Shift in k else 1))


def number(minimum,maximum,value,decimals=2):
    n=QDoubleSpinBox();n.setRange(minimum,maximum);n.setDecimals(decimals);n.setValue(value);n.setKeyboardTracking(False);return n


class Studio(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle('Forest Camera Studio');self.resize(1280,850)
        self.process=None;self.network=None;self.buffer=None;self.log_file=None;self.sequence=0
        self.ready=False;self.status={};self.syncing=False;self.started=0.;self.last_motion=time.perf_counter()
        self.scene_path=ROOT/'flow_forest.blend';self.last_project=None;self.closing=False
        self.render_process=None;self.render_log=None;self.render_output=None
        self.preview=Preview();self.setCentralWidget(self.preview)
        self.build_controls()
        self.preview.camera_shortcut.connect(lambda index:self.camera_list.setCurrentIndex(index) if index<self.camera_list.count() else None)
        self.preview.capture_shortcut.connect(self.screenshot)
        self.frame_timer=QTimer(self);self.frame_timer.timeout.connect(self.read_preview);self.frame_timer.start(33)
        self.motion_timer=QTimer(self);self.motion_timer.timeout.connect(self.drive);self.motion_timer.start(40)
        self.status_timer=QTimer(self);self.status_timer.timeout.connect(self.poll);self.status_timer.start(900)
        self.statusBar().showMessage('右ドラッグ: 視線 | WASD: 移動 | Q/E: 上下 | 矢印: 視線 | Shift: 高速 | ホイール: 速度')

    def button(self,text,callback,layout):
        b=QPushButton(text);b.clicked.connect(callback);layout.addWidget(b);return b

    def build_controls(self):
        toolbar=self.addToolBar('Project');toolbar.setMovable(False)
        for title,func in [('シーンを開く',self.choose_scene),('Blenderを起動',self.start_backend),('プロジェクトを保存',self.save_project),('PNG撮影',self.screenshot)]:
            toolbar.addAction(title,func)
        self.render_action=toolbar.addAction('高品質PNG',self.render_still)
        dock=QDockWidget('カメラとシーン',self);dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        panel=QWidget();layout=QVBoxLayout(panel);tabs=QTabWidget();layout.addWidget(tabs)
        camera_tab=QWidget();v=QVBoxLayout(camera_tab)
        self.camera_list=QComboBox();self.camera_list.currentIndexChanged.connect(self.switch_camera);v.addWidget(self.camera_list)
        row=QHBoxLayout();self.button('現在位置を複製',self.add_camera,row);self.button('名前変更',self.rename_camera,row);v.addLayout(row)
        group=QGroupBox('レンズ / 被写界深度');form=QFormLayout(group)
        self.lens=number(8,300,40,1);self.lens.setSuffix(' mm');form.addRow('焦点距離',self.lens)
        self.dof=QCheckBox('有効');form.addRow('被写界深度',self.dof)
        self.focus=number(.01,10000,10,2);self.focus.setSuffix(' m');form.addRow('ピント距離',self.focus)
        self.aperture=number(.1,128,2.8,1);form.addRow('F値',self.aperture)
        self.focus_object=QComboBox();self.focus_object.addItem('対象未指定（手動）',None);form.addRow('ピント対象',self.focus_object)
        self.focus_object.setToolTip('対象を選ぶと被写界深度とオートフォーカスが有効になります。対象の原点に追従します。')
        self.autofocus=QCheckBox('対象にピントを追従');self.autofocus.setEnabled(False);form.addRow('オートフォーカス',self.autofocus)
        use_selected=QPushButton('選択オブジェクトをピント対象にする');use_selected.clicked.connect(self.focus_selected_object);form.addRow(use_selected)
        self.focus_hint=QLabel('手動ピント');self.focus_hint.setWordWrap(True);form.addRow(self.focus_hint)
        for control in [self.lens,self.focus,self.aperture]:control.valueChanged.connect(self.update_lens)
        self.dof.toggled.connect(self.update_lens);self.focus_object.currentIndexChanged.connect(self.select_focus_target)
        self.autofocus.toggled.connect(self.toggle_autofocus)
        v.addWidget(group)
        quality=QGroupBox('プレビュー');f=QFormLayout(quality)
        self.preview_mode=QComboBox();self.preview_mode.addItems(['EEVEE（光・被写界深度）','高速（材質色のみ）']);self.preview_mode.currentIndexChanged.connect(self.update_quality);f.addRow('描画方式',self.preview_mode)
        self.quality=QComboBox();self.quality.addItems(['軽量 480×320','標準 720×480','高品質 1080×720']);self.quality.setCurrentIndex(1)
        self.quality.currentIndexChanged.connect(self.update_quality);f.addRow('解像度',self.quality)
        self.target_fps=QSpinBox();self.target_fps.setRange(1,30);self.target_fps.setValue(15);self.target_fps.valueChanged.connect(self.update_quality);f.addRow('目標FPS',self.target_fps)
        self.adaptive=QCheckBox('移動中は解像度を下げる');self.adaptive.setChecked(True);self.adaptive.toggled.connect(self.update_quality);f.addRow(self.adaptive)
        v.addWidget(quality);v.addStretch();tabs.addTab(camera_tab,'カメラ')

        objects=QWidget();v=QVBoxLayout(objects)
        info=QLabel('位置・回転・スケールのキーフレームを編集できます。\n歩行などのリグ動作編集は今後追加します。');info.setWordWrap(True);v.addWidget(info)
        self.object_list=QComboBox();self.object_list.currentIndexChanged.connect(self.load_object);v.addWidget(self.object_list)
        self.transforms={}
        form=QFormLayout()
        for label,key,default,low,high in [('位置','location',0,-10000,10000),('回転°','rotation',0,-36000,36000),('スケール','scale',1,.001,1000)]:
            row=QHBoxLayout();controls=[]
            for axis in 'XYZ':
                control=number(low,high,default);control.setPrefix(axis+' ');row.addWidget(control);controls.append(control)
            self.transforms[key]=controls;form.addRow(label,row)
        v.addLayout(form);self.button('変形を適用',lambda:self.apply_object(False),v)
        self.button('現在フレームにキーフレームを追加',lambda:self.apply_object(True),v);v.addStretch();tabs.addTab(objects,'オブジェクト')
        self.connection=QLabel('未接続');self.connection.setWordWrap(True);layout.addWidget(self.connection)
        dock.setWidget(panel);self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,dock);dock.setMinimumWidth(340)

        timeline=QDockWidget('共通タイムライン',self);timeline.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        panel=QWidget();v=QVBoxLayout(panel);row=QHBoxLayout()
        self.play=self.button('▶ 再生',self.toggle_play,row)
        self.record=self.button('● カメラ移動を記録',self.toggle_record,row)
        self.button('カメラのキーを追加',lambda:self.send('key_camera'),row)
        self.start_frame=QSpinBox();self.start_frame.setRange(-100000,100000);self.start_frame.setValue(1)
        self.end_frame=QSpinBox();self.end_frame.setRange(-100000,100000);self.end_frame.setValue(250)
        self.fps=QSpinBox();self.fps.setRange(1,120);self.fps.setValue(24)
        for title,c in [('開始',self.start_frame),('終了',self.end_frame),('FPS',self.fps)]:row.addWidget(QLabel(title));row.addWidget(c);c.editingFinished.connect(self.update_timeline)
        v.addLayout(row);row=QHBoxLayout();self.frame=QSpinBox();self.frame.setRange(-100000,100000);self.frame.setValue(1);self.frame.editingFinished.connect(self.seek)
        self.slider=QSlider(Qt.Orientation.Horizontal);self.slider.setRange(1,250);self.slider.valueChanged.connect(self.slider_seek)
        row.addWidget(QLabel('フレーム'));row.addWidget(self.frame);row.addWidget(self.slider,1);v.addLayout(row)
        timeline.setWidget(panel);self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,timeline)

    def choose_scene(self):
        path,_=QFileDialog.getOpenFileName(self,'Blenderシーンを開く',str(ROOT),'Blender (*.blend)')
        if not path:return
        if self.process and self.process.poll() is None:
            QMessageBox.information(self,'シーンの変更','現在のアプリを閉じて再起動してから、別のシーンを開いてください。必要な変更は先に保存してください。');return
        self.scene_path=Path(path);self.preview.message=self.scene_path.name;self.preview.update()

    def start_backend(self):
        if self.process and self.process.poll() is None:return
        if not self.scene_path.exists():QMessageBox.warning(self,'シーンがありません','シーンを開くから .blend を選択してください。');return
        prefs=self.scene_path.with_suffix('.studio.json')
        if prefs.exists():
            try:
                data=json.loads(prefs.read_text(encoding='utf-8'))
                self.quality.setCurrentIndex(max(0,min(2,int(data.get('quality',1)))))
                self.preview_mode.setCurrentIndex(max(0,min(1,int(data.get('mode',0)))))
                self.target_fps.setValue(int(data.get('target_fps',15)))
                self.adaptive.setChecked(bool(data.get('adaptive',True)))
                self.preview.speed=max(.05,min(50,float(data.get('speed',3))))
            except (ValueError,OSError,TypeError):self.statusBar().showMessage('アプリ設定を読めなかったため標準設定を使います。',10000)
        exe=Path(os.environ.get('BLENDER_EXE',str(DEFAULT_BLENDER)))
        if not exe.exists():
            value,_=QFileDialog.getOpenFileName(self,'blender.exe を選択','C:/Program Files','Blender (blender.exe)')
            if not value:return
            exe=Path(value)
        if self.network:
            self.network.running=False;self.network.wait(4000)
            if self.network.isRunning():return
        if self.buffer:self.buffer.close()
        if self.log_file:self.log_file.close()
        self.token=secrets.token_hex(24);self.buffer_name='ForestStudio_'+secrets.token_hex(10);self.buffer=open_buffer(self.buffer_name)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
        log_dir=ROOT/'studio_output';log_dir.mkdir(exist_ok=True);self.log_path=log_dir/'blender_bridge.log';self.log_file=self.log_path.open('w',encoding='utf-8')
        command=[str(exe),str(self.scene_path),'--python',str(ROOT/'studio'/'bridge.py'),'--','--port',str(self.port),'--token',self.token,'--buffer',self.buffer_name]
        self.process=subprocess.Popen(command,stdout=self.log_file,stderr=subprocess.STDOUT)
        self.blender_exe=exe
        self.network=Network(self.port,self.token);self.network.response.connect(self.on_response);self.network.failed.connect(self.on_error);self.network.start()
        self.ready=False;self.sequence=0;self.started=time.monotonic();self.preview.message='Blenderの起動・シェーダー準備中…';self.preview.update();self.connection.setText('起動中: '+self.scene_path.name)

    def send(self,op,**data):
        if self.network and (self.ready or op=='status'):self.network.post(op,**data)

    def poll(self):
        if self.render_process and self.render_process.poll() is not None:
            success=self.render_process.returncode==0 and self.render_output.exists()
            self.render_log.close();self.render_log=None;self.render_process=None;self.render_action.setEnabled(True)
            self.statusBar().showMessage(('高品質PNG保存: ' if success else 'レンダー失敗。ログを確認: ')+str(self.render_output if success else self.render_output.with_suffix('.log')),15000)
        if not self.process:return
        if self.process.poll() is not None:
            self.ready=False;self.connection.setText('Blenderが終了しました。ログ: '+str(self.log_path));return
        self.send('status')

    def read_preview(self):
        if not self.buffer:return
        result=read_frame(self.buffer,self.sequence)
        if result:
            w,h,pixels,self.sequence,stamp=result
            self.preview.image=QImage(pixels,w,h,w*4,QImage.Format.Format_RGBA8888).mirrored(False,True).copy()
            self.preview.message=f'{self.camera_list.currentText()} | {w}×{h} | {self.status.get("preview_fps",0):.1f} fps | 速度 {self.preview.speed:.2f} m/s'
            self.preview.update()

    def drive(self):
        now=time.perf_counter();dt=min(now-self.last_motion,.15);self.last_motion=now
        motion=self.preview.motion(dt)
        if self.ready and motion:self.send('drive',**motion)

    def refill(self,combo,entries,current):
        if [(combo.itemData(i),combo.itemText(i)) for i in range(combo.count())]!=[(x['id'],x['name']) for x in entries]:
            combo.clear()
            for entry in entries:combo.addItem(entry['name'],entry['id'])
        index=combo.findData(current)
        if index>=0:combo.setCurrentIndex(index)

    def on_response(self,op,result):
        if op=='render_snapshot':
            self.render_log=self.render_output.with_suffix('.log').open('w',encoding='utf-8')
            command=[str(self.blender_exe),'--background',result['path'],'--python',str(ROOT/'studio'/'render_frame.py'),'--','--output',str(self.render_output)]
            self.render_process=subprocess.Popen(command,stdout=self.render_log,stderr=subprocess.STDOUT)
            self.statusBar().showMessage('高品質PNGを書き出しています。プレビュー操作は続けられます。',15000);return
        if op=='object_state':
            self.syncing=True
            for key,controls in self.transforms.items():
                for c,val in zip(controls,result[key]):c.setValue(val)
            self.syncing=False;return
        if op=='save':
            prefs=Path(result['path']).with_suffix('.studio.json')
            try:prefs.write_text(json.dumps(dict(version=1,quality=self.quality.currentIndex(),mode=self.preview_mode.currentIndex(),target_fps=self.target_fps.value(),adaptive=self.adaptive.isChecked(),speed=self.preview.speed),ensure_ascii=False,indent=2),encoding='utf-8')
            except OSError as exc:self.statusBar().showMessage('Blenderシーンは保存済み。アプリ設定の保存失敗: '+str(exc),12000);return
            self.statusBar().showMessage('保存しました: '+result['path'],10000);return
        if 'cameras' not in result:return
        first=not self.ready;self.ready=True;self.status=result;self.syncing=True
        self.refill(self.camera_list,result['cameras'],result['camera'])
        selected_object=self.object_list.currentData();self.refill(self.object_list,result['objects'],selected_object)
        focus_entries=[dict(id=None,name='対象未指定（手動）')]+result['objects'];self.refill(self.focus_object,focus_entries,result.get('focus_target',result['focus_object']))
        for c,key in [(self.lens,'lens'),(self.focus,'focus'),(self.aperture,'aperture')]:
            if not c.hasFocus():c.setValue(result[key])
        self.dof.setChecked(result['dof']);self.autofocus.setChecked(result.get('autofocus',bool(result['focus_object'])))
        self.autofocus.setEnabled(self.focus_object.currentData() is not None);self.focus.setEnabled(not self.autofocus.isChecked())
        if self.autofocus.isChecked():
            self.focus_hint.setText(('追従中: ' if result['dof'] else '被写界深度OFF / 対象設定は保持: ')+self.focus_object.currentText())
        else:self.focus_hint.setText('手動ピント（AFをOFFにすると直前のピント距離を保持）')
        for c,key in [(self.start_frame,'start'),(self.end_frame,'end'),(self.fps,'fps'),(self.frame,'frame')]:
            if not c.hasFocus():c.setValue(int(result[key]))
        self.slider.setRange(result['start'],result['end'])
        if not self.slider.isSliderDown():self.slider.setValue(result['frame'])
        self.play.setText('■ 停止' if result['playing'] else '▶ 再生');self.record.setText('■ 記録終了' if result['recording'] else '● カメラ移動を記録')
        self.syncing=False
        if result['preview_error']:self.connection.setText('描画エラー: '+result['preview_error'])
        else:self.connection.setText('接続済み / '+('EEVEE' if result.get('mode')=='eevee' else '高速表示（光・被写界深度は未反映）')+' / '+self.scene_path.name)
        if first:self.update_quality();self.load_object()

    def on_error(self,op,message):
        if op=='render_snapshot':self.render_action.setEnabled(True)
        if op=='status' and not self.ready:
            if time.monotonic()-self.started>60:self.connection.setText('接続待ち。Blenderウィンドウとログを確認してください。\n'+str(self.log_path))
            return
        if op=='drive':self.connection.setText('移動エラー: '+message);return
        self.statusBar().showMessage(op+': '+message,12000)
        if op!='status':QMessageBox.warning(self,'操作できませんでした',message)

    def switch_camera(self):
        if not self.syncing and self.camera_list.currentData():self.send('switch_camera',id=self.camera_list.currentData())

    def add_camera(self):
        name,ok=QInputDialog.getText(self,'カメラ追加','名前',text='Camera')
        if ok:self.send('add_camera',name=name)

    def rename_camera(self):
        name,ok=QInputDialog.getText(self,'カメラ名','名前',text=self.camera_list.currentText())
        if ok:self.send('rename_camera',name=name)

    def update_lens(self):
        if not self.syncing:self.send('lens',lens=self.lens.value(),dof=self.dof.isChecked(),focus=self.focus.value(),aperture=self.aperture.value(),focus_object=self.focus_object.currentData(),autofocus=self.autofocus.isChecked())

    def select_focus_target(self):
        if self.syncing:return
        target=self.focus_object.currentData()
        self.syncing=True
        self.autofocus.setEnabled(target is not None);self.autofocus.setChecked(target is not None)
        if target:self.dof.setChecked(True)
        self.syncing=False;self.update_lens()

    def toggle_autofocus(self,enabled):
        if self.syncing:return
        self.syncing=True
        if enabled:self.dof.setChecked(True)
        self.syncing=False;self.update_lens()

    def focus_selected_object(self):
        if not self.ready:return
        index=self.focus_object.findData(self.object_list.currentData())
        if index>0:
            self.syncing=True;self.focus_object.setCurrentIndex(index);self.syncing=False
            self.select_focus_target()

    def update_quality(self):
        w,h=[(480,320),(720,480),(1080,720)][self.quality.currentIndex()]
        self.send('preview',width=w,height=h,fps=self.target_fps.value(),mode='eevee' if self.preview_mode.currentIndex()==0 else 'solid',adaptive=self.adaptive.isChecked())

    def update_timeline(self,playing=None):
        if self.syncing:return
        self.send('timeline',start=self.start_frame.value(),end=self.end_frame.value(),fps=self.fps.value(),frame=self.frame.value(),playing=self.status.get('playing',False) if playing is None else playing)

    def toggle_play(self):self.update_timeline(not self.status.get('playing',False))
    def toggle_record(self):self.send('record',enabled=not self.status.get('recording',False))
    def seek(self):self.update_timeline(False)
    def slider_seek(self,value):
        if self.syncing:return
        self.frame.setValue(value);self.seek()

    def load_object(self):
        if not self.syncing and self.object_list.currentData():self.send('object_state',id=self.object_list.currentData())

    def apply_object(self,keyframe):
        if self.object_list.currentData():self.send('object_transform',id=self.object_list.currentData(),keyframe=keyframe,**{key:[c.value() for c in controls] for key,controls in self.transforms.items()})

    def screenshot(self):
        if self.preview.image.isNull():QMessageBox.information(self,'撮影','プレビューが表示されてから撮影してください。');return
        folder=ROOT/'studio_output'/'screenshots';folder.mkdir(parents=True,exist_ok=True)
        path=folder/('camera_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.png')
        if self.preview.image.save(str(path)):self.statusBar().showMessage('PNG保存: '+str(path),10000)
        else:QMessageBox.warning(self,'保存エラー','画像を保存できませんでした。')

    def save_project(self):
        if not self.ready:return
        suggested=ROOT/'studio_output'/(self.scene_path.stem+'_studio.blend')
        path,_=QFileDialog.getSaveFileName(self,'作業用シーンを保存',str(suggested),'Blender (*.blend)')
        if not path:return
        if not path.lower().endswith('.blend'):path+='.blend'
        if Path(path).resolve()==self.scene_path.resolve():
            reply=QMessageBox.question(self,'元シーンを上書き','元のシーンに上書きしますか？')
            if reply!=QMessageBox.StandardButton.Yes:return
        self.last_project=Path(path);self.send('save',path=path)

    def render_still(self):
        if not self.ready:return
        folder=ROOT/'studio_output'/'renders';folder.mkdir(parents=True,exist_ok=True)
        self.render_output=folder/('render_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.png')
        self.render_action.setEnabled(False)
        self.send('render_snapshot',path=str(self.render_output.with_suffix('.blend')))

    def closeEvent(self,event):
        if self.closing:event.ignore();return
        if self.ready:
            message='終了すると未保存の変更は失われます。'
            if self.render_process and self.render_process.poll() is None:message+=' 実行中の高品質レンダーも停止します。'
            answer=QMessageBox.question(self,'終了',message+' 終了しますか？',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes:event.ignore();return
        self.closing=True;self.motion_timer.stop();self.status_timer.stop();self.preview.keys.clear()
        if self.render_process and self.render_process.poll() is None:self.render_process.terminate()
        if self.render_log:self.render_log.close();self.render_log=None
        if self.process and self.process.poll() is None:
            try:request(self.port,self.token,dict(op='shutdown'),timeout=2)
            except Exception:pass
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.terminate()
        if self.network:
            self.network.running=False;self.network.wait(4000)
            if self.network.isRunning():
                self.closing=False;event.ignore();QTimer.singleShot(1000,self.close);return
        if self.buffer:self.buffer.close();self.buffer=None
        if self.log_file:self.log_file.close()
        event.accept()


def main():
    app=QApplication(sys.argv);app.setStyle('Fusion')
    app.setStyleSheet('QWidget { font-size: 12px; } QGroupBox { margin-top: 12px; padding-top: 12px; } QPushButton { padding: 6px; }')
    window=Studio()
    if len(sys.argv)>1 and sys.argv[1].lower().endswith('.blend'):window.scene_path=Path(sys.argv[1]).resolve()
    window.show();sys.exit(app.exec())


if __name__=='__main__':main()
