#!/usr/bin/env python3
"""
HandControl: the gesture engine behind STARK.

Framework: MediaPipe hand landmarks + pinch-distance gestures with separate
left/right hand roles, after Marina Budarina's Hand Tracking Demo.

  python handcontrol.py              run the STARK desktop app (macOS)
  python handcontrol.py --no-preview run hidden (both fists to pause)
  python handcontrol.py --dry-run    practice mode: shows gestures, controls nothing
"""
import argparse
import json
import os
import sys
import time

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

from backends import make_backend, MAC_KEYS, MAC_MOD_KEYS, ALIASES
from gestures import (Engine, THUMB_TIP, INDEX_TIP, TIPS, ACTIONS, MOUSE_ACTIONS,
                      cheat_sheet)

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "models", "hand_landmarker.task")
CONFIG = os.path.join(HERE, "config.json")
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")

CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
               (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15),
               (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]

ASCII = {"⌘-": "Cmd-", "⇧-": "Shift-", "⌘": "Cmd-", "⇧": "Shift-", "←": "<-", "→": "->", "↑": "up", "↓": "down",
         "·": "|", "—": "-"}


def ascii(s):
    for a, b in ASCII.items():
        s = s.replace(a, b)
    return s


def load_config():
    if not os.path.exists(CONFIG):
        return {}, {}
    with open(CONFIG) as f:
        raw = json.load(f)
    bindings = {k: v for k, v in raw.pop("bindings", {}).items() if not k.startswith("_")}
    cfg = {k: v for k, v in raw.items() if not k.startswith("_")}
    return cfg, bindings


def check_bindings(bindings):
    ok = set(MAC_KEYS) | set(MAC_MOD_KEYS) | set(ALIASES)
    for gesture, action in bindings.items():
        if not action or action in ACTIONS or action in MOUSE_ACTIONS:
            continue
        bad = [k for k in action.lower().split("+") if k not in ok]
        if bad:
            print(f"  config: '{gesture}' -> '{action}': unknown key(s) {bad}, ignoring")
            bindings[gesture] = None


def ensure_model():
    if os.path.exists(MODEL):
        return
    import urllib.request
    os.makedirs(os.path.dirname(MODEL), exist_ok=True)
    print("Downloading hand model (8 MB)...")
    urllib.request.urlretrieve(MODEL_URL, MODEL)


def camera_devices():
    """Camera names in the same order OpenCV numbers them on a Mac."""
    if sys.platform != "darwin":
        return []
    try:
        import AVFoundation as AV
        devs = list(AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeVideo)) + \
            list(AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeMuxed))
        # OpenCV AVFoundation indexes devices in uniqueID order, not discovery order.
        devs.sort(key=lambda d: str(d.uniqueID()))
        return [{'name': str(d.localizedName()), 'id': str(d.uniqueID()),
                 'phone': ('continuity' in str(d.deviceType()).lower()
                           or 'iphone' in str(d.localizedName()).lower()
                           or 'desk view' in str(d.localizedName()).lower())} for d in devs]
    except Exception:
        return []


def list_cameras():
    return [d['name'] for d in camera_devices()]


def pick_camera(setting, names):
    """Legacy name/index selection; auto never falls back to a phone."""
    if isinstance(setting, int) or str(setting).isdigit():
        index = int(setting)
        return index if 0 <= index < len(names) else -1
    if setting and setting != 'auto':
        for i, name in enumerate(names):
            if str(setting).lower() in name.lower(): return i
        return -1
    for want in ('facetime', 'macbook', 'built-in', 'builtin'):
        for i, name in enumerate(names):
            if want in name.lower() and 'iphone' not in name.lower(): return i
    return next((i for i,n in enumerate(names)
                 if 'iphone' not in n.lower() and 'desk view' not in n.lower()), -1)


def resolve_camera(setting, devices):
    if isinstance(setting, str) and setting.startswith('id:'):
        return next((i for i,d in enumerate(devices) if d['id'] == setting[3:]), -1)
    if setting == 'auto' or setting is None:
        safe = [(i,d) for i,d in enumerate(devices) if not d['phone']]
        for i,d in safe:
            if any(w in d['name'].lower() for w in ('facetime','macbook','built-in','builtin')): return i
        return safe[0][0] if safe else -1
    return pick_camera(setting, [d['name'] for d in devices])


def open_camera(index):
    if index < 0:
        raise RuntimeError("No selected webcam is available. Choose a camera in Settings.")
    api = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, api)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    return cap


def text(img, s, org, scale=0.45, color=(255, 255, 255), thick=1, center=False):
    font = cv2.FONT_HERSHEY_SIMPLEX
    if center:
        (w, _), _ = cv2.getTextSize(s, font, scale, thick)
        org = (int(org[0] - w / 2), int(org[1]))
    cv2.putText(img, s, (org[0] + 1, org[1] + 1), font, scale, (0, 0, 0), thick, cv2.LINE_AA)
    cv2.putText(img, s, org, font, scale, color, thick, cv2.LINE_AA)


def wrap(s, scale, width):
    """Split a cheat-sheet line at commas so it fits."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    out, cur = [], ""
    for part in s.split(", "):
        cand = f"{cur}, {part}" if cur else part
        if cur and cv2.getTextSize(cand, font, scale, 1)[0][0] > width:
            out.append(cur + ",")
            cur = "    " + part
        else:
            cur = cand
    return out + [cur]


def draw_hud(frame, hands, st, fps, dry, toast, show_help, help_lines, cam_name=""):
    h, w = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 30), (20, 20, 20), -1)
    if show_help:
        cv2.rectangle(overlay, (0, 30), (w, h), (15, 15, 15), -1)
    frame[:] = cv2.addWeighted(overlay, 0.75 if show_help else 0.6, frame,
                               0.25 if show_help else 0.4, 0)

    if not show_help:
        for hand in hands:
            pts = [(int(x * w), int(y * h)) for x, y in hand["lm"]]
            for a, b in CONNECTIONS:
                cv2.line(frame, pts[a], pts[b], (255, 255, 255), 1, cv2.LINE_AA)
            info = st.get("right" if hand["label"] == "Right" else "left") or {}
            pinch = info.get("pinch")
            # The demo's signature: a thumb-to-finger line that firms up on pinch.
            t = pts[THUMB_TIP]
            f = pts[TIPS[pinch]] if pinch else pts[INDEX_TIP]
            cv2.line(frame, t, f, (255, 255, 255), 3 if pinch else 1, cv2.LINE_AA)
            for p in (t, f):
                cv2.circle(frame, p, 7 if pinch else 5, (255, 255, 255), -1, cv2.LINE_AA)
            who = "R" if hand["label"] == "Right" else "L"
            mode = ascii(info.get("mode") or "")
            text(frame, f"{who}: {mode}" if mode else who,
                 (pts[0][0], min(h - 8, pts[0][1] + 22)), 0.5, center=True)

    if st.get("paused"):
        state, col = "PAUSED  (both fists to resume)", (80, 180, 255)
    elif dry:
        state, col = "PRACTICE  (not controlling)", (80, 220, 255)
    else:
        state, col = "ACTIVE", (120, 230, 120)
    text(frame, state, (10, 20), 0.5, col)
    text(frame, f"H help  C camera  {fps:3.0f} fps", (w - 200, 20), 0.42, (200, 200, 200))
    if st.get("dictating"):
        cv2.rectangle(frame, (w // 2 - 92, 38), (w // 2 + 92, 68), (40, 40, 210), -1)
        cv2.circle(frame, (w // 2 - 70, 53), 6, (255, 255, 255), -1, cv2.LINE_AA)
        text(frame, "DICTATING", (w // 2 + 8, 60), 0.6, center=True, thick=2)

    if show_help:
        step = 17 if len(help_lines) <= 22 else 15
        y = 50
        for left_s, right_s in help_lines:
            if left_s.isupper():
                y += 4
                text(frame, ascii(left_s), (14, y), 0.42, (130, 200, 255))
                text(frame, ascii(right_s), (190, y), 0.42, (130, 200, 255))
            else:
                text(frame, ascii(left_s), (22, y), 0.4, (190, 190, 190))
                for k, part in enumerate(wrap(ascii(right_s), 0.4, w - 200)):
                    if k:
                        y += step - 1
                    text(frame, part, (190, y), 0.4, (245, 245, 245))
            y += step
        return

    if st.get("hold", 0) > 0:
        cx, cy, r = w // 2, h // 2, 34
        cv2.ellipse(frame, (cx, cy), (r, r), -90, 0, 360 * st["hold"],
                    (255, 255, 255), 3, cv2.LINE_AA)
        text(frame, ascii(st["hold_label"]), (cx, cy + r + 22), 0.55, center=True)

    if toast:
        text(frame, ascii(toast), (w // 2, h - 24), 0.9, (255, 255, 255), 2, center=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", default=None,
                    help='"auto", a number, or part of a camera name (overrides config)')
    ap.add_argument("--legacy-preview", action="store_true", help="Use the original OpenCV preview")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if sys.platform == "darwin" and os.environ.get("DEX_SELFTEST"):
        from desktop import selftest
        return selftest(os.environ["DEX_SELFTEST"])
    if sys.platform == "darwin" and not args.no_preview and not args.legacy_preview:
        from desktop import run
        return run(args)

    win = "HandControl"
    preview = not args.no_preview
    if preview:
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win, 560, 420)
        try:
            cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)
        except Exception:
            pass

    def notice(lines):
        """Print a message and show it in the preview window. Returns the key pressed."""
        if not preview:
            return -1
        img = np.full((480, 640, 3), 24, np.uint8)
        y = 150
        for k, ln in enumerate(lines):
            text(img, ln, (320, y), 0.75 if k == 0 else 0.5,
                 (255, 255, 255) if k == 0 else (210, 210, 210), 1, center=True)
            y += 44 if k == 0 else 28
        text(img, "Q to quit", (320, 440), 0.45, (150, 150, 150), center=True)
        cv2.imshow(win, img)
        return cv2.waitKey(30) & 0xFF

    notice(["Starting HandControl..."])
    print("Starting HandControl...")
    ensure_model()
    cfg, bindings = load_config()
    check_bindings(bindings)
    cam_names = list_cameras()
    cam_setting = args.camera if args.camera is not None else cfg.pop("camera", "auto")
    cfg.pop("camera", None)
    cam_index = pick_camera(cam_setting, cam_names)
    if cam_names:
        print("Cameras: " + ", ".join(f"{i}={n}" for i, n in enumerate(cam_names)))
    cam_name = cam_names[cam_index] if cam_index < len(cam_names) else f"camera {cam_index}"
    print(f"Using {cam_name}  (press C in the preview to switch)")

    if sys.platform == "darwin" and not args.dry_run:
        try:
            from ApplicationServices import (AXIsProcessTrusted, AXIsProcessTrustedWithOptions,
                                             kAXTrustedCheckOptionPrompt)
            if not AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
                print("\nmacOS needs to let Terminal control the mouse.\n"
                      "System Settings > Privacy & Security > Accessibility: turn on Terminal.\n"
                      "If it's already on: quit Terminal (Cmd+Q) and start HandControl again.\n")
                while not AXIsProcessTrusted():
                    k = notice(["Allow Terminal to control the mouse",
                                "System Settings > Privacy & Security > Accessibility",
                                "Turn on Terminal. This screen continues by itself.",
                                "Already on? Quit Terminal (Cmd+Q) and start again."])
                    if k in (ord("q"), 27):
                        return 1
                    if not preview:
                        return 1
                    time.sleep(0.5)
                print("Accessibility permission OK.")
        except ImportError:
            pass

    backend = make_backend(args.dry_run)
    sw, sh = backend.screen_size()
    engine = Engine(backend, backend, sw, sh, cfg, bindings)
    help_lines = cheat_sheet(engine.bindings)
    show_help = args.dry_run
    toast, toast_until = "", 0.0

    notice(["Loading hand tracking..."])
    options = vision.HandLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=MODEL),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.7,   # same as the demo
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5)
    landmarker = vision.HandLandmarker.create_from_options(options)

    # The first time, macOS asks for camera permission while we wait, so retry.
    cap, waited = None, 0.0
    while True:
        cap = open_camera(cam_index)
        if cap.isOpened():
            ok = False
            for _ in range(40):          # cameras need a moment to warm up
                ok, _ = cap.read()
                if ok:
                    break
                cv2.waitKey(1)
                time.sleep(0.05)
            if ok:
                break
            cap.release()
        if waited == 0.0:
            print("Waiting for the camera. If macOS asks, click Allow.")
        if waited > 60:
            print("Couldn't open the camera. System Settings > Privacy & Security > "
                  "Camera: turn on Terminal, quit Terminal (Cmd+Q), and start again.")
            notice(["Couldn't open the camera",
                    "System Settings > Privacy & Security > Camera",
                    "Turn on Terminal, quit Terminal (Cmd+Q), start again."])
            cv2.waitKey(4000)
            return 1
        k = notice(["Waiting for the camera...",
                    "If macOS asks to use the camera, click Allow.",
                    "Camera light off? Check System Settings >",
                    "Privacy & Security > Camera > Terminal."])
        if k in (ord("q"), 27):
            return 1
        time.sleep(1.0)
        waited += 1.5
    print("Camera OK.")

    print(f"HandControl running on a {sw}x{sh} screen. "
          "In the preview: H = gesture cheat sheet, P = pause, Q = quit.")
    t0 = time.monotonic()
    last_ts = -1
    bad_since = None
    fps, last = 0.0, time.monotonic()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                bad_since = bad_since or time.monotonic()
                if time.monotonic() - bad_since > 3:
                    if notice(["The camera stopped sending video",
                               "Is another app using it? Close it and wait."]) in (ord("q"), 27):
                        break
                time.sleep(0.05)
                continue
            bad_since = None
            frame = cv2.flip(frame, 1)  # mirror, so handedness labels are yours
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            ts = int((time.monotonic() - t0) * 1000)
            if ts <= last_ts:
                ts = last_ts + 1
            last_ts = ts
            res = landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)

            hands = []
            for lms, hd in zip(res.hand_landmarks, res.handedness):
                # MediaPipe names hands as if the picture weren't mirrored. We mirror
                # it, so flip the name to match your real left and right hand.
                label = "Left" if hd[0].category_name == "Right" else "Right"
                hands.append({"label": label, "lm": [(p.x, p.y) for p in lms]})
            now = time.monotonic()
            st = engine.update(hands, now, aspect=w / h)
            if st.get("event"):
                print("  ", ascii(st["event"]))
                toast, toast_until = st["event"], now + 1.2
            if now > toast_until:
                toast = ""

            dt = now - last
            last = now
            fps = 0.9 * fps + 0.1 * (1 / dt if dt > 0 else 0)

            if not args.no_preview:
                draw_hud(frame, hands, st, fps, args.dry_run, toast, show_help, help_lines,
                         cam_name)
                cv2.imshow(win, frame)
                k = cv2.waitKey(1) & 0xFF
                if k in (ord("q"), 27):
                    break
                if k == ord("h"):
                    show_help = not show_help
                if k == ord("c"):
                    count = max(len(cam_names), 2)
                    for _ in range(count):
                        cam_index = (cam_index + 1) % count
                        new = open_camera(cam_index)
                        if new.isOpened() and new.read()[0]:
                            cap.release()
                            cap = new
                            break
                        new.release()
                    cam_name = (cam_names[cam_index] if cam_index < len(cam_names)
                                else f"camera {cam_index}")
                    print(f"Switched to {cam_name}. To keep it, set \"camera\": "
                          f"\"{cam_name}\" in config.json")
                    toast, toast_until = cam_name, time.monotonic() + 2.0
                if k == ord("p"):
                    engine.paused = not engine.paused
                    engine._release_all()
    except KeyboardInterrupt:
        pass
    finally:
        engine.shutdown()
        cap.release()
        landmarker.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
