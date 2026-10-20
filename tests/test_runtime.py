"""Exercise off/practice/control lifecycle without a camera or OS input."""
import pathlib
import sys
import types
import unittest
from unittest.mock import patch, Mock
import numpy as np
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import handcontrol as hc
from runtime import CaptureWorker
from mediapipe.tasks.python import vision

class RuntimeTests(unittest.TestCase):
    def exercise(self, mode):
        worker=CaptureWorker(types.SimpleNamespace(dry_run=False,camera=None))
        if mode!='off':worker.request('mode',mode)
        frames=[]
        original=worker.publish
        def publish(**data):
            frames.append(data)
            original(**data)
            if mode=='off' and data.get('clear'):worker.stop.set()
        worker.publish=publish
        cap=Mock();cap.read.return_value=(True,np.zeros((48,64,3),np.uint8))
        tracker=Mock();tracker.detect_for_video.return_value=types.SimpleNamespace(hand_landmarks=[],handedness=[])
        backend=Mock();backend.screen_size.return_value=(100,100)
        engine=Mock();engine.paused=False;engine.sw=engine.sh=100
        def update(*args,**kwargs):worker.stop.set();return {}
        engine.update.side_effect=update
        permissions=types.SimpleNamespace(AVCaptureDevice=types.SimpleNamespace(authorizationStatusForMediaType_=lambda _:3),AVMediaTypeVideo='video')
        with patch.dict(sys.modules,{'AVFoundation':permissions,'ApplicationServices':types.SimpleNamespace(AXIsProcessTrusted=lambda:True)}), \
             patch.object(hc,'camera_devices',return_value=[{'name':'FaceTime HD Camera','id':'builtin','phone':False}]),patch.object(hc,'ensure_model'), \
             patch.object(hc,'open_camera',return_value=cap) as opened, \
             patch.object(vision.HandLandmarker,'create_from_options',return_value=tracker) as created, \
             patch('backends.make_backend',return_value=backend) as make_backend, \
             patch('gestures.Engine',return_value=engine):
            worker.capture()
        return frames,cap,tracker,engine,opened,created,make_backend

    def test_off_never_opens_camera_or_runs_recognition(self):
        frames,cap,tracker,engine,opened,created,backend=self.exercise('off')
        opened.assert_not_called();created.assert_not_called();engine.update.assert_not_called()
        self.assertTrue(any(x.get('clear') for x in frames))

    def test_practice_uses_dry_backend_and_cleans_up(self):
        frames,cap,tracker,engine,opened,created,backend=self.exercise('practice')
        backend.assert_called_once_with(True)
        self.assertEqual(tracker.detect_for_video.call_count,1)
        cap.release.assert_called_once();tracker.close.assert_called_once();engine.shutdown.assert_called_once()

    def test_control_uses_control_backend_and_cleans_up(self):
        frames,cap,tracker,engine,opened,created,backend=self.exercise('control')
        backend.assert_called_once_with(False)
        cap.release.assert_called_once();tracker.close.assert_called_once();engine.shutdown.assert_called_once()

if __name__=='__main__':unittest.main()
