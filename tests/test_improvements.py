import pathlib,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from displays import bounds,nearest_point
from clap import DoubleClap
from gesture_guard import GestureGuard
from gestures import FingerPinch
import handcontrol as hc

class DisplayTests(unittest.TestCase):
    def test_left_and_above_origin(self):
        r=[(0,0,1920,1080),(-1280,-200,1280,1024)]
        self.assertEqual(bounds(r),(-1280,-200,3200,1280))
        self.assertEqual(nearest_point(-500,20,r),(-500,20))
    def test_gap_snaps_to_visible_pixel(self):
        self.assertEqual(nearest_point(150,50,[(0,0,100,100),(200,0,100,100)]),(200,50))
    def test_vertical_stack(self):
        self.assertEqual(bounds([(0,-900,1440,900),(0,0,1440,900)]),(0,-900,1440,1800))

class CameraTests(unittest.TestCase):
    def setUp(self):
        self.devices=[{'name':'Kenny’s camera','id':'phone','phone':True},
                      {'name':'FaceTime HD Camera','id':'laptop','phone':False}]
    def test_auto_avoids_phone_even_with_custom_name(self):
        self.assertEqual(hc.resolve_camera('auto',self.devices),1)
        self.assertEqual(hc.resolve_camera('auto',self.devices[:1]),-1)
    def test_stable_id_survives_reorder(self):
        self.assertEqual(hc.resolve_camera('id:laptop',self.devices[::-1]),0)
    def test_missing_selection_does_not_fallback(self):
        self.assertEqual(hc.resolve_camera('id:missing',self.devices),-1)
    def test_phone_explicit_opt_in(self):
        self.assertEqual(hc.resolve_camera('id:phone',self.devices),0)
    def test_legacy_auto_never_returns_phone(self):
        self.assertEqual(hc.pick_camera('auto',['iPhone']),-1)

class GuardTests(unittest.TestCase):
    def setUp(self):
        self.g=GestureGuard();self.hand={'label':'Right','lm':[(.4,.6)]*21}
    def arm(self):
        with patch('gesture_guard.classify',return_value='open'):
            for t in (0,.1,.2,.3,.4): self.result=self.g.filter([self.hand],t)
    def test_open_palm_required(self):
        with patch('gesture_guard.classify',return_value='point'):
            self.assertEqual(self.g.filter([self.hand],0),[])
        self.arm();self.assertEqual(self.result,[self.hand])
    def test_hand_in_front_of_face_keeps_control(self):
        self.arm()
        with patch('gesture_guard.classify',return_value='point'):
            self.assertEqual(self.g.filter([self.hand],.45,[(.3,.5,.2,.2)]),[self.hand])
            self.assertEqual(self.g.filter([self.hand],.5,[(.3,.5,.2,.2)]),[self.hand])
        self.assertEqual(self.g.reason,'')
    def test_lost_hand_cannot_return_pinched(self):
        self.arm();self.g.filter([],.45)
        with patch('gesture_guard.classify',return_value='pinch'):
            self.assertEqual(self.g.filter([self.hand],.5),[])
    def test_jump_is_rejected(self):
        self.arm();h=dict(self.hand,lm=[(.8,.6)]*21)
        self.assertEqual(self.g.filter([h],.45),[])
    def test_short_pinch_noise_does_not_click(self):
        p=FingerPinch(.25,.4,seconds=.08)
        ratio=dict(index=.1,middle=1,ring=1,pinky=1)
        self.assertEqual(p.update(ratio,False,0),(None,None))
        self.assertEqual(p.update(ratio,False,.03),(None,None))
        self.assertEqual(p.update(ratio,False,.09),('index',None))

class ClapTests(unittest.TestCase):
    def run_signal(self,pulses,seconds=2):
        d=DoubleClap();events=[]
        for i in range(int(seconds*100)):
            t=i/100
            loud=any(a<=t<b for a,b in pulses)
            if d.feed(t,.7 if loud else .005,.15 if loud else .002):events.append(t)
        return events
    def test_two_claps(self):self.assertEqual(len(self.run_signal([(.3,.33),(.65,.68)])),1)
    def test_single_clap(self):self.assertEqual(self.run_signal([(.3,.33)]),[])
    def test_sustained_loud_audio(self):self.assertEqual(self.run_signal([(.3,.9),(1.2,1.8)]),[])
    def test_too_far_apart(self):self.assertEqual(self.run_signal([(.3,.33),(1.1,1.13)]),[])
    def test_cooldown(self):self.assertEqual(len(self.run_signal([(.3,.33),(.65,.68),(.9,.93),(1.2,1.23)])),1)
    def test_audio_gap_clears_pending_clap(self):
        d=DoubleClap()
        for t,p,r in [(0,0,0),(.1,0,0),(.2,.7,.15),(.23,0,0),(.6,0,0),(.7,.7,.15),(.73,0,0)]:
            self.assertFalse(d.feed(t,p,r))

if __name__=='__main__':unittest.main()
