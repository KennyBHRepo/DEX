"""A single worker owns capture, recognition and all generated input events."""
import collections
import queue
import threading
import time
import traceback
from session import Session

class CaptureWorker(threading.Thread):
    def __init__(self, args):
        super().__init__(name='STARK camera', daemon=True)
        self.args = args
        self.commands = queue.Queue()
        self.messages = queue.Queue(maxsize=2)
        self.stop = threading.Event()
        self.session = Session(args.dry_run)
        # Revocation is immediate even if a frame is currently in inference.
        self.output_allowed = threading.Event()

    def request(self, command, value):
        self.output_allowed.clear()
        self.commands.put((command, value))

    def publish(self, **data):
        try:
            self.messages.put_nowait(data)
        except queue.Full:
            try:
                self.messages.get_nowait()
            except queue.Empty:
                pass
            self.messages.put_nowait(data)

    def run(self):
        import objc
        with objc.autorelease_pool():
            self.capture()

    def capture(self):
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python as tasks
        from mediapipe.tasks.python import vision
        from ApplicationServices import AXIsProcessTrusted
        import AVFoundation as AV
        import handcontrol as hc
        from backends import make_backend
        from gestures import Engine
        cap = tracker = engine = None
        index = 0
        cfg, bindings, names = {}, {}, []
        last_ts = -1
        event, event_until = '', 0
        try:
            cfg, bindings = hc.load_config()
            hc.check_bindings(bindings)
            devices = hc.camera_devices()
            names = [d["name"] for d in devices]
            setting = self.args.camera if self.args.camera is not None else cfg.pop('camera', 'auto')
            cfg.pop('camera', None)
            index = hc.resolve_camera(setting, devices)
            from gestures import DEFAULTS, DEFAULT_BINDINGS
            cfg = dict(DEFAULTS, **cfg)
            cfg.setdefault('gesture_guard', True)
            cfg.setdefault('clap_wake', False)
            cfg['camera'] = setting
            from gesture_guard import GestureGuard
            guard = GestureGuard()
            accepted_labels = set()
            display_time = -1
            bindings = dict(DEFAULT_BINDINGS, **bindings)
            self.publish(mode='off', ready=True, cfg=cfg, bindings=bindings, names=names, index=index)
            failures, was_off = 0, False
            while not self.stop.is_set():
                changed = False
                while not self.commands.empty():
                    command, value = self.commands.get_nowait()
                    changed = True
                    if engine is not None:
                        engine.shutdown()
                        engine = None
                    if cap is not None:
                        cap.release()
                        cap = None
                    if command == 'mode':
                        self.session.set_mode(value)
                    elif command == 'configure':
                        cfg.update(value)
                        self.session.set_mode('off')
                    elif command == 'bindings':
                        # Full edited map from the Controls screen (None = unassigned).
                        bindings = dict(value)
                        self.session.set_mode('off')
                    elif command == 'select':
                        setting = value
                        cfg['camera'] = setting
                        index = hc.resolve_camera(setting, devices)
                        self.session.set_mode('off')
                    elif command == 'suspend':
                        self.session.suspend(value)
                    failures = 0
                    guard = GestureGuard()
                    accepted_labels = set()
                    event = ''
                common = dict(mode=self.session.mode, cfg=cfg, bindings=bindings,
                              names=names, index=index, ready=True)
                if not self.session.recognizing:
                    if cap is not None:
                        cap.release()
                        cap = None
                    if engine is not None:
                        engine.shutdown()
                        engine = None
                    if changed or not was_off:
                        self.publish(**common, clear=True)
                    was_off = True
                    self.stop.wait(.04)
                    continue
                was_off = False
                permission = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo)
                if permission != 3:
                    self.session.set_mode('off')
                    self.publish(**dict(common, mode='off'), clear=True, error='Camera access is needed. Open Privacy Settings, allow STARK under Camera, then try again.')
                    continue
                if self.session.mode == 'control' and not AXIsProcessTrusted():
                    self.session.set_mode('off')
                    self.publish(**dict(common, mode='off'), clear=True, error='Allow STARK under Accessibility in Privacy Settings to control your Mac. The walkthrough works without it.')
                    continue
                if cap is None:
                    devices = hc.camera_devices()
                    names = [d['name'] for d in devices]
                    index = hc.resolve_camera(setting, devices)
                    if index < 0:
                        self.session.set_mode('off')
                        self.publish(**dict(common, mode='off'), clear=True,
                            error='Your selected webcam is unavailable. Choose a connected camera in Settings. STARK will not switch to your phone automatically.')
                        continue
                if tracker is None:
                    self.publish(**common, loading=True, message='Getting ready to see your hands…')
                    hc.ensure_model()
                    if self.stop.is_set() or not self.commands.empty():
                        continue
                    tracker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                        base_options=tasks.BaseOptions(model_asset_path=hc.MODEL),
                        running_mode=vision.RunningMode.VIDEO, num_hands=2,
                        min_hand_detection_confidence=.8, min_hand_presence_confidence=.75,
                        min_tracking_confidence=.75))
                if cap is None:
                    cap = hc.open_camera(index)
                    self.publish(**common, loading=True, message='Opening your camera…')
                if engine is None:
                    backend = make_backend(self.session.mode != 'control')
                    if self.session.mode == 'practice':
                        backend.log = collections.deque(maxlen=128)
                    engine_cfg = dict(cfg)
                    if cfg.get('gesture_guard'):
                        engine_cfg['pinch_confirm_s'] = .08
                    engine = Engine(backend, backend, *backend.screen_size(), engine_cfg, bindings)
                    self.output_allowed.set()
                ok, frame = cap.read()
                if not ok:
                    engine.shutdown()
                    failures += 1
                    if failures >= 30:
                        self.session.set_mode('off')
                        self.publish(**dict(common, mode='off'), clear=True, error='The camera isn’t available. Close other camera apps or choose another camera in Settings, then try again.')
                    self.stop.wait(.1)
                    continue
                failures = 0
                frame = cv2.flip(frame, 1)
                h, w = frame.shape[:2]
                last_ts = max(last_ts + 1, int(time.monotonic() * 1000))
                result = tracker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                    data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), last_ts)
                if self.stop.is_set() or not self.commands.empty() or not self.output_allowed.is_set():
                    continue
                hands = [{'label': 'Left' if hd[0].category_name == 'Right' else 'Right',
                          'lm': [(p.x, p.y) for p in lm]}
                         for lm, hd in zip(result.hand_landmarks, result.handedness)]
                now = time.monotonic()
                if self.session.mode == 'practice':
                    backend.log.clear()
                if now-display_time > 2:
                    size = backend.screen_size()
                    if size != (engine.sw, engine.sh):
                        engine.shutdown()
                        engine.sw, engine.sh = size
                        engine.fx.reset(); engine.fy.reset()
                    display_time = now
                if cfg.get('gesture_guard'):
                    filtered = guard.filter(hands, now, aspect=w/h)
                    from gestures import classify
                    if len(hands) == 2 and all(classify([(x*w/h,y) for x,y in hand['lm']]) == 'fist' for hand in hands):
                        filtered = hands  # emergency stop must never need re-arming
                    labels = {h["label"] for h in filtered}
                    if accepted_labels - labels:
                        # Cancel held clicks/keys and inertia before feeding any remaining hand.
                        engine.shutdown()
                        engine.scroll_vel = (0,0)
                    accepted_labels = labels
                    st = engine.update(filtered, now, aspect=w/h)
                else:
                    st = engine.update(hands, now, aspect=w/h)
                if engine.paused:
                    # The inherited both-fists gesture can turn recognition OFF,
                    # but cannot secretly re-enable it once the camera is off.
                    engine.shutdown()
                    self.session.set_mode('off')
                    self.publish(**dict(common, mode='off'), clear=True)
                    continue
                pointer = None
                role = 'Left' if cfg.get('swap_hands') else 'Right'
                for hand in hands:
                    pts = [(int(x*w), int(y*h)) for x,y in hand['lm']]
                    for a,b in hc.CONNECTIONS:
                        cv2.line(frame, pts[a], pts[b], (210,230,245), 2, cv2.LINE_AA)
                    for point in pts:
                        cv2.circle(frame, point, 3, (180,205,255), -1, cv2.LINE_AA)
                    if hand['label'] == role:
                        pointer = hand['lm'][8]
                        cv2.circle(frame, pts[8], 12, (100,160,255), 2, cv2.LINE_AA)
                if st.get('event'):
                    event, event_until = st['event'], now+1.8
                log = list(backend.log) if self.session.mode == 'practice' else []
                encoded, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
                self.publish(**common, image=jpg.tobytes() if encoded else None,
                    status=st, hands=len(hands), pointer=pointer, time=now,
                    guard=guard.reason if cfg.get('gesture_guard') else '',
                    did_click=any(x[0] in ('click','down') for x in log),
                    did_scroll=any(x[0]=='scroll' and (x[1] or x[2]) for x in log),
                    event=event if now<event_until else '')
        except Exception as error:
            traceback.print_exc()
            self.publish(mode='off', clear=True, fatal=True,
                         error=f'STARK needs a fresh start. {error}')
        finally:
            if engine is not None:
                engine.shutdown()
            if cap is not None:
                cap.release()
            if tracker is not None:
                tracker.close()
