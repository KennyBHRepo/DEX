"""
Gesture engine for HandControl.

Framework: Marina Budarina's Hand Tracking Demo (budarina-canvas.replit.app).
It uses MediaPipe hand landmarks, the thumb-to-index pinch distance as the
core signal, an open-hand test (fingertips beyond their middle joints), and a
separate job for each hand. HandControl extends that into a full trackpad
replacement:

  RIGHT HAND = the mouse     point to move, pinch fingers for click types
  LEFT HAND  = shortcuts     pinch to scroll, finger taps, hand-shape swipes

This module is pure logic (no camera, no OS calls) so it can be unit tested.
"""
import math
import time

WRIST, THUMB_MCP, THUMB_IP, THUMB_TIP = 0, 2, 3, 4
INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP = 5, 9, 13, 17
TIPS = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}
PIPS = {"index": 6, "middle": 10, "ring": 14, "pinky": 18}
ORDER = ("index", "middle", "ring", "pinky")
INDEX_TIP, MIDDLE_TIP = 8, 12

# ---------------------------------------------------------------- actions
# Any binding can be one of these names or a raw combo like "cmd+shift+t".
ACTIONS = {
    "copy": "cmd+c", "cut": "cmd+x", "paste": "cmd+v",
    "paste_match_style": "cmd+alt+shift+v", "undo": "cmd+z", "redo": "cmd+shift+z",
    "select_all": "cmd+a", "find": "cmd+f",
    "next_tab": "ctrl+tab", "prev_tab": "ctrl+shift+tab", "new_tab": "cmd+t",
    "close_tab": "cmd+w", "reopen_tab": "cmd+shift+t", "reload": "cmd+r",
    "back": "cmd+[", "forward": "cmd+]", "address_bar": "cmd+l",
    "next_desktop": "ctrl+right", "prev_desktop": "ctrl+left",
    "mission_control": "ctrl+up", "app_expose": "ctrl+down",
    "next_window": "cmd+`", "minimize": "cmd+m", "spotlight": "cmd+space",
    "screenshot": "cmd+shift+4", "zoom_in": "cmd+=", "zoom_out": "cmd+-",
    "enter": "return", "escape": "esc", "page_down": "pagedown", "page_up": "pageup",
    "top": "cmd+up", "bottom": "cmd+down",
}
MOUSE_ACTIONS = {"right_click": ("right", ()), "cmd_click": ("left", ("cmd",)),
                 "shift_click": ("left", ("shift",)), "opt_click": ("left", ("alt",)),
                 "double_click": ("left", ())}
LABELS = {"cmd_click": "⌘-click (new tab)", "shift_click": "⇧-click (extend)",
          "paste_match_style": "paste plain", "app_expose": "app windows",
          "next_tab": "next tab", "prev_tab": "previous tab"}

DEFAULT_BINDINGS = {
    # Right hand: thumb to finger pinches (index is always click / drag).
    "right.middle.pinch": "right_click",
    "right.ring.pinch": "cmd_click",
    "right.pinky.pinch": "shift_click",
    # Left hand: thumb to finger taps (index is always scroll).
    "left.middle.tap": "copy",
    "left.middle.hold": "cut",
    "left.ring.tap": "paste",
    "left.ring.hold": "paste_match_style",
    "left.pinky.tap": "undo",
    "left.pinky.hold": "redo",
    # Left hand shapes + swipes. Trackpad convention: swipe left = next.
    "left.open.swipe_left": "next_tab",
    "left.open.swipe_right": "prev_tab",
    "left.peace.swipe_left": "forward",
    "left.peace.swipe_right": "back",
    "left.three.swipe_left": "next_desktop",
    "left.three.swipe_right": "prev_desktop",
    "left.three.swipe_up": "mission_control",
    "left.three.swipe_down": "app_expose",
    "left.point.hold": "new_tab",
    "left.thumbs_down.hold": "close_tab",
    # Both hands.
    "both.open.hold": "spotlight",
}

DEFAULTS = {
    "pinch_press": 0.25,        # thumb-to-finger distance / hand size to press
    "pinch_release": 0.40,      # ...and to let go
    "active_left": 0.18, "active_right": 0.82,   # camera region -> whole screen
    "active_top": 0.12, "active_bottom": 0.72,
    "smoothing_min_cutoff": 1.2,
    "smoothing_beta": 0.03,
    "click_settle_s": 0.15,     # cursor holds still this long after a pinch
    "double_click_s": 0.40,
    "double_click_px": 40,
    "precision_gain": 0.25,     # cursor speed while left fist is held
    "scroll_gain": 2600,
    "scroll_inertia": True,
    "invert_scroll": False,
    "tap_hold_s": 0.55,         # left finger pinch longer than this = "hold"
    "pose_hold_s": 0.6,         # hand shape held still this long = "hold"
    "swipe_speed": 2.2,         # hand-lengths per second
    "swipe_distance": 1.2,      # hand-lengths
    "swipe_cooldown_s": 0.7,
    "app_switcher": True,       # left thumbs-up = ⌘-Tab switcher
    "app_switch_step": 0.7,     # hand-lengths of sideways travel per app
    "pause_hold_s": 1.0,
    "zoom_step": 1.18,
    "swap_hands": False,        # true if you'd rather point with your left
    # Dictation (Wispr Flow): 🤙 "call me" sign with either hand.
    "dictation": True,
    "dictation_mode": "hold",   # "hold": talk while the sign is up (Fn held)
                                # "hands_free": flash the sign to start, again to stop
    "dictation_key": "fn",              # Wispr push-to-talk key
    "dictation_hands_free_key": "fn+space",  # Wispr hands-free shortcut
    "dictation_grace_s": 0.5,   # sign can drop out this long without stopping
    "dictation_max_s": 600,     # safety: stop after 10 minutes
}


# ---------------------------------------------------------------- geometry
def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def hand_scale(lm):
    """Wrist to middle knuckle. Every threshold is relative to this, so it
    works at any distance from the camera (the demo used a fixed 0.065)."""
    return max(1e-6, dist(lm[WRIST], lm[MIDDLE_MCP]))


def palm_center(lm):
    pts = [lm[i] for i in (WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)]
    return (sum(p[0] for p in pts) / 5, sum(p[1] for p in pts) / 5)


def pinch_ratios(lm):
    s = hand_scale(lm)
    return {f: dist(lm[THUMB_TIP], lm[TIPS[f]]) / s for f in ORDER}


def pinch_ratio(lm, tip=INDEX_TIP):
    return dist(lm[THUMB_TIP], lm[tip]) / hand_scale(lm)


def extended(lm, f):
    w = lm[WRIST]
    return dist(lm[TIPS[f]], w) > dist(lm[PIPS[f]], w) * 1.08


def curled(lm, f):
    w = lm[WRIST]
    return dist(lm[TIPS[f]], w) < dist(lm[PIPS[f]], w)


def thumb_out(lm):
    return dist(lm[THUMB_TIP], lm[INDEX_MCP]) / hand_scale(lm) > 0.55


def classify(lm):
    """Hand shape: open, three, peace, point, call, fist, thumbs_up, thumbs_down, other."""
    ext = tuple(extended(lm, f) for f in ORDER)
    if all(ext):
        return "open"
    if ext == (True, True, True, False):
        return "three"
    if ext == (True, True, False, False):
        return "peace"
    if ext == (True, False, False, False):
        return "point"
    if ext == (False, False, False, True) and thumb_out(lm):
        return "call"             # 🤙 thumb + pinky out: the "phone" sign
    if all(curled(lm, f) for f in ORDER):
        if thumb_out(lm):
            dy = (lm[THUMB_TIP][1] - lm[THUMB_MCP][1]) / hand_scale(lm)
            if dy < -0.35:
                return "thumbs_up"
            if dy > 0.35:
                return "thumbs_down"
        return "fist"
    return "other"


def is_open(lm):
    return classify(lm) == "open"


def is_fist(lm):
    return classify(lm) == "fist"


# ---------------------------------------------------------------- helpers
class OneEuro:
    """One Euro filter: smooth when still, responsive when moving fast."""

    def __init__(self, min_cutoff=1.2, beta=0.03, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self):
        self.x = self.dx = self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self.t is None:
            self.x, self.dx, self.t = x, 0.0, t
            return x
        dt = max(1e-3, t - self.t)
        self.t = t
        a_d = self._alpha(self.d_cutoff, dt)
        self.dx = a_d * (x - self.x) / dt + (1 - a_d) * self.dx
        a = self._alpha(self.min_cutoff + self.beta * abs(self.dx), dt)
        self.x = a * x + (1 - a) * self.x
        return self.x


class Stable:
    """A value only changes after the new value shows up N frames in a row."""

    def __init__(self, frames=3):
        self.frames, self.cur, self.cand, self.n, self.since = frames, None, None, 0, 0.0

    def update(self, v, t):
        if v == self.cur:
            self.cand, self.n = None, 0
        else:
            self.n = self.n + 1 if v == self.cand else 1
            self.cand = v
            if self.n >= self.frames:
                self.cur, self.cand, self.n, self.since = v, None, 0, t
        return self.cur

    def reset(self):
        self.cur, self.cand, self.n = None, None, 0


class FingerPinch:
    """Which finger (if any) the thumb is pinching, with hysteresis and a
    two-frame debounce. The thumb belongs to whichever fingertip is closest."""

    def __init__(self, press, release, frames=2, seconds=0):
        self.press, self.release, self.frames = press, release, frames
        self.seconds, self.candidate_since = seconds, 0.0
        self.finger, self.cand, self.n, self.t0 = None, None, 0, 0.0

    def update(self, ratios, blocked, t):
        started = ended = None
        if self.finger and (blocked or ratios[self.finger] > self.release):
            ended, self.finger = self.finger, None
        if self.finger is None and ended is None:
            f = min(ratios, key=ratios.get)
            if not blocked and ratios[f] < self.press:
                if f != self.cand: self.candidate_since = t
                self.n = self.n + 1 if f == self.cand else 1
                self.cand = f
                if self.n >= self.frames and t-self.candidate_since >= self.seconds:
                    self.finger, self.t0, started = f, t, f
                    self.cand, self.n = None, 0
            else:
                self.cand, self.n = None, 0
        return started, ended

    def reset(self):
        ended, self.finger, self.cand, self.n = self.finger, None, None, 0
        return ended


class Swipe:
    """A steady sweep over several frames. Tracking jumps don't count."""

    def __init__(self):
        self.hist = []

    def reset(self):
        self.hist = []

    def update(self, p, t, scale, speed, distance, window=0.35):
        self.hist = [h for h in self.hist if t - h[0] <= window] + [(t, p[0], p[1])]
        if len(self.hist) < 4:
            return None
        t0, x0, y0 = self.hist[0]
        t1, x1, y1 = self.hist[-1]
        dx, dy = (x1 - x0) / scale, (y1 - y0) / scale
        if abs(dx) >= 2 * abs(dy):
            axis, d = 1, dx
        elif abs(dy) >= 2 * abs(dx):
            axis, d = 2, dy
        else:
            return None
        steps = [(b[axis] - a[axis]) / scale for a, b in zip(self.hist, self.hist[1:])]
        if max(abs(s) for s in steps) > 1.0:          # teleport, not a swipe
            return None
        if any(s * d < 0 and abs(s) > 0.06 for s in steps):  # changed direction
            return None
        if abs(d) < distance or abs(d) / max(1e-3, t1 - t0) < speed:
            return None
        self.hist = []
        if axis == 1:
            return "left" if d < 0 else "right"
        return "up" if d < 0 else "down"


class StillHold:
    """Fires once when the same thing is held fairly still for `seconds`."""

    def __init__(self):
        self.key, self.t0, self.anchor, self.fired = None, 0.0, None, False

    def update(self, key, p, t, scale, seconds):
        if key != self.key:
            self.key, self.t0, self.anchor, self.fired = key, t, p, False
            return False
        if key is None:
            return False
        if dist(p, self.anchor) / scale > 0.5:
            self.anchor, self.t0 = p, t
            return False
        if not self.fired and t - self.t0 >= seconds:
            self.fired = True
            return True
        return False

    def progress(self, t, seconds):
        if self.key is None or self.fired:
            return 0.0
        return min(1.0, (t - self.t0) / seconds)


class Hold:
    def __init__(self, seconds):
        self.seconds, self.since, self.fired = seconds, None, False

    def update(self, cond, t):
        if not cond:
            self.since, self.fired = None, False
            return False
        if self.since is None:
            self.since = t
        if not self.fired and t - self.since >= self.seconds:
            self.fired = True
            return True
        return False

    def progress(self, t):
        if self.since is None or self.fired:
            return 0.0
        return min(1.0, (t - self.since) / self.seconds)


def label_for(action):
    return LABELS.get(action, action.replace("_", " "))


# ---------------------------------------------------------------- engine
class Engine:
    def __init__(self, mouse, keys, screen_w, screen_h, cfg=None, bindings=None):
        self.mouse, self.keys = mouse, keys
        self.sw, self.sh = screen_w, screen_h
        self.cfg = dict(DEFAULTS)
        self.cfg.update(cfg or {})
        self.bindings = dict(DEFAULT_BINDINGS)
        self.bindings.update(bindings or {})
        self.bindings = {k: v for k, v in self.bindings.items() if v}
        c = self.cfg
        self.paused = False
        self.fx = OneEuro(c["smoothing_min_cutoff"], c["smoothing_beta"])
        self.fy = OneEuro(c["smoothing_min_cutoff"], c["smoothing_beta"])
        self.r_pinch = FingerPinch(c["pinch_press"], c["pinch_release"], seconds=c.get("pinch_confirm_s", 0))
        self.l_pinch = FingerPinch(c["pinch_press"], c["pinch_release"], seconds=c.get("pinch_confirm_s", 0))
        self.r_pose, self.l_pose = Stable(3), Stable(3)
        self.l_swipe = Swipe()
        self.l_hold = StillHold()
        self.both_hold = StillHold()
        self.pause_hold = Hold(c["pause_hold_s"])
        self.button_down = False
        self.last_pinch_t = -10.0
        self.last_up_t, self.last_up_pos, self.click_count = -10.0, (0, 0), 1
        self.cursor = (screen_w / 2, screen_h / 2)
        self.offset = (0.0, 0.0)
        self.prec = None            # (abs_target0, cursor0) while precision is on
        self.scroll_prev = None
        self.scroll_vel = (0.0, 0.0)
        self.l_tap_fired = False
        self.zooming, self.zoom_base = False, None
        self.switching, self.switch_x = False, 0.0
        self.l_last_pose = None
        self.swipe_cool = 0.0
        self.last_t = None
        self.status = {}
        self.dictating = False
        self.dict_seen = self.dict_start = 0.0
        self.call_was = False

    # ---------- actions ----------
    def do(self, name, st):
        if not name:
            return
        if name in MOUSE_ACTIONS:
            button, mods = MOUSE_ACTIONS[name]
            if name == "double_click":
                self.mouse.down("left", *self.cursor, clicks=1)
                self.mouse.up("left", *self.cursor, clicks=1)
                self.mouse.down("left", *self.cursor, clicks=2)
                self.mouse.up("left", *self.cursor, clicks=2)
            else:
                self.mouse.click(button, *self.cursor, mods=mods)
        else:
            combo = ACTIONS.get(name, name)
            self.keys.hotkey(*combo.lower().split("+"))
        st["event"] = label_for(name)

    def _bound(self, key, st):
        if key in self.bindings:
            self.do(self.bindings[key], st)
            return True
        return False

    # ---------- utilities ----------
    def _map(self, p):
        c = self.cfg
        u = (p[0] - c["active_left"]) / (c["active_right"] - c["active_left"])
        v = (p[1] - c["active_top"]) / (c["active_bottom"] - c["active_top"])
        return (min(1, max(0, u)) * (self.sw - 1), min(1, max(0, v)) * (self.sh - 1))

    def _clamp(self, x, y):
        return min(self.sw - 1, max(0, x)), min(self.sh - 1, max(0, y))

    def _end_switcher(self):
        if self.switching:
            self.keys.mod_up("cmd")
            self.switching = False

    def _stop_dictation(self, st=None):
        if self.dictating:
            if self.cfg["dictation_mode"] == "hold":
                self.keys.hold(self.cfg["dictation_key"], False)
            else:
                self.keys.hotkey(*self.cfg["dictation_hands_free_key"].split("+"))
            self.dictating = False
            if st is not None:
                st["event"] = "dictation stopped"

    def _release_all(self):
        self._stop_dictation()
        if self.button_down:
            self.mouse.up("left", *self.cursor)
            self.button_down = False
        self._end_switcher()
        self.r_pinch.reset()
        self.l_pinch.reset()
        self.zooming = False
        self.scroll_prev = None
        self.scroll_vel = (0.0, 0.0)

    def shutdown(self):
        self._release_all()

    # ---------- main ----------
    def update(self, hands, t=None, aspect=4 / 3):
        """hands: [{"label": "Left"|"Right", "lm": [(x, y) * 21]}] in mirrored,
        normalized image coords. Returns a status dict for the HUD."""
        t = time.monotonic() if t is None else t
        dt = 0.033 if self.last_t is None else min(0.2, max(1e-3, t - self.last_t))
        self.last_t = t
        c = self.cfg

        left = right = None
        for h in hands:
            label = h["label"]
            if c["swap_hands"]:
                label = "Left" if label == "Right" else "Right"
            lm = [(x * aspect, y) for x, y in h["lm"]]   # square up the geometry
            hand = {"lm": lm, "raw": h["lm"], "scale": hand_scale(lm),
                    "shape": classify(lm), "ratios": pinch_ratios(lm)}
            if label == "Right" and right is None:
                right = hand
            elif label == "Left" and left is None:
                left = hand
        if right:
            right["pose"] = self.r_pose.update(right["shape"], t)
        else:
            self.r_pose.reset()
        if left:
            left["pose"] = self.l_pose.update(left["shape"], t)
        else:
            self.l_pose.reset()

        st = {"paused": self.paused, "right": None, "left": None, "event": None,
              "dictating": self.dictating,
              "hold": 0.0, "hold_label": ""}

        # Both fists held: pause / resume (the only gesture that works paused).
        both_fists = bool(left and right and left["shape"] == "fist"
                          and right["shape"] == "fist")
        if self.pause_hold.update(both_fists, t):
            self.paused = not self.paused
            self._release_all()
            st["event"] = "paused" if self.paused else "resumed"
        if both_fists:
            st["hold"] = self.pause_hold.progress(t)
            st["hold_label"] = "resume" if self.paused else "pause"
        st["paused"] = self.paused
        if self.paused:
            self.status = st
            return st

        self._dictation(left, right, st, t)

        # Both palms open, held still: Spotlight by default.
        both_open = bool(left and right and left["pose"] == "open" and right["pose"] == "open")
        key = "both.open.hold" if both_open and "both.open.hold" in self.bindings else None
        mid = palm_center(left["lm"]) if left else (0, 0)
        if self.both_hold.update(key, mid, t, left["scale"] if left else 1, c["pose_hold_s"]):
            self._bound(key, st)
        if key:
            st["hold"] = self.both_hold.progress(t, c["pose_hold_s"])
            st["hold_label"] = label_for(self.bindings[key])

        self._left(left, right, both_open, st, t, dt)
        self._right(right, left, st, t, dt)
        self._inertia(dt)
        self.status = st
        return st

    # ---------- dictation (Wispr Flow) ----------
    def _dictation(self, left, right, st, t):
        c = self.cfg
        if not c["dictation"]:
            return
        call = any(h and h.get("pose") == "call" for h in (left, right))
        if call:
            self.dict_seen = t
        if c["dictation_mode"] == "hold":
            if call and not self.dictating:
                self.keys.hold(c["dictation_key"], True)
                self.dictating, self.dict_start = True, t
                st["event"] = "dictating"
            elif self.dictating and (t - self.dict_seen > c["dictation_grace_s"]
                                     or t - self.dict_start > c["dictation_max_s"]):
                self._stop_dictation(st)
        else:  # hands_free: each fresh 🤙 toggles
            fresh = call and not self.call_was
            if call:
                self.call_was = True
            elif t - self.dict_seen > c["dictation_grace_s"]:
                self.call_was = False
            if fresh:
                self.keys.hotkey(*c["dictation_hands_free_key"].split("+"))
                self.dictating = not self.dictating
                self.dict_start = t
                st["event"] = "dictating" if self.dictating else "dictation stopped"
            elif self.dictating and t - self.dict_start > c["dictation_max_s"]:
                self._stop_dictation(st)
        st["dictating"] = self.dictating

    # ---------- left hand: shortcuts ----------
    def _left(self, left, right, both_open, st, t, dt):
        c = self.cfg
        if left is None:
            if self.l_pinch.reset() == "index":
                self.scroll_prev = None
            self._end_switcher()
            self.l_swipe.reset()
            self.l_hold.update(None, (0, 0), t, 1, 1)
            self.l_last_pose = None
            return
        lm, raw, s = left["lm"], left["raw"], left["scale"]
        pose = left["pose"]
        info = {"pose": pose, "mode": "dictate" if pose == "call" else (pose or ""),
                "pinch": None}
        st["left"] = info

        blocked = left["shape"] in ("fist", "thumbs_up", "thumbs_down") or self.switching
        started, ended = self.l_pinch.update(left["ratios"], blocked, t)
        finger = self.l_pinch.finger
        info["pinch"] = finger

        # Index pinch + move: scroll, like grabbing the page.
        p = _pinch_point(raw)
        if started == "index":
            self.scroll_prev, self.scroll_vel = p, (0.0, 0.0)
        if finger == "index":
            if self.zooming:
                info["mode"] = "zoom"
            else:
                info["mode"] = "scroll"
                if self.scroll_prev is not None:
                    sign = -1 if c["invert_scroll"] else 1
                    dx = (p[0] - self.scroll_prev[0]) * c["scroll_gain"] * sign
                    dy = (p[1] - self.scroll_prev[1]) * c["scroll_gain"] * sign
                    if abs(dx) + abs(dy) > 0.5:
                        self.mouse.scroll(dx, dy)
                    self.scroll_vel = (0.6 * self.scroll_vel[0] + 0.4 * dx / dt,
                                       0.6 * self.scroll_vel[1] + 0.4 * dy / dt)
                self.scroll_prev = p
        if ended == "index":
            self.scroll_prev = None
            if self.zooming or not c["scroll_inertia"]:
                self.scroll_vel = (0.0, 0.0)

        # Middle / ring / pinky: tap or hold.
        if started in ("middle", "ring", "pinky"):
            self.l_tap_fired = False
            if f"left.{started}.hold" not in self.bindings:
                self._bound(f"left.{started}.tap", st)   # no hold bound: fire now
                self.l_tap_fired = True
        if finger in ("middle", "ring", "pinky"):
            info["mode"] = self.bindings.get(f"left.{finger}.tap", finger).replace("_", " ")
            hold_key = f"left.{finger}.hold"
            if not self.l_tap_fired and hold_key in self.bindings:
                st["hold"] = min(1.0, (t - self.l_pinch.t0) / c["tap_hold_s"])
                st["hold_label"] = label_for(self.bindings[hold_key])
                if t - self.l_pinch.t0 >= c["tap_hold_s"]:
                    self._bound(hold_key, st)
                    self.l_tap_fired = True
        if ended in ("middle", "ring", "pinky") and not self.l_tap_fired:
            self._bound(f"left.{ended}.tap", st)

        pc = palm_center(lm)
        if finger or started or ended:
            self.l_swipe.reset()
            self.l_hold.update(None, pc, t, s, 1)
            self.l_last_pose = None
            return

        if pose != self.l_last_pose:
            self.l_swipe.reset()
            self.l_last_pose = pose

        # Thumbs up: ⌘-Tab app switcher. Slide sideways to pick, drop the pose to switch.
        if c["app_switcher"] and pose == "thumbs_up":
            info["mode"] = "app switcher"
            if not self.switching:
                self.keys.mod_down("cmd")
                self.keys.hotkey("cmd", "tab")
                self.switching, self.switch_x = True, pc[0]
                st["event"] = "app switcher"
            else:
                step = c["app_switch_step"] * s
                while pc[0] - self.switch_x > step:
                    self.keys.hotkey("cmd", "tab")
                    self.switch_x += step
                while self.switch_x - pc[0] > step:
                    self.keys.hotkey("cmd", "shift", "tab")
                    self.switch_x -= step
            return
        self._end_switcher()

        # Left fist: precision mode for the right-hand cursor.
        if pose == "fist" and right is not None and right.get("pose") != "fist":
            info["mode"] = "precision"

        # Hand-shape swipes.
        if pose and any(k.startswith(f"left.{pose}.swipe_") for k in self.bindings):
            d = self.l_swipe.update(pc, t, s, c["swipe_speed"], c["swipe_distance"])
            if d and t > self.swipe_cool and self._bound(f"left.{pose}.swipe_{d}", st):
                self.swipe_cool = t + c["swipe_cooldown_s"]
                self.l_hold.update(None, pc, t, s, 1)

        # Hand-shape holds.
        hold_key = f"left.{pose}.hold"
        if both_open or hold_key not in self.bindings:
            hold_key = None
        if self.l_hold.update(hold_key, pc, t, s, c["pose_hold_s"]):
            self._bound(hold_key, st)
        if hold_key:
            prog = self.l_hold.progress(t, c["pose_hold_s"])
            if prog > 0.15:
                st["hold"], st["hold_label"] = prog, label_for(self.bindings[hold_key])

    # ---------- right hand: the mouse ----------
    def _right(self, right, left, st, t, dt):
        c = self.cfg
        if right is None:
            if self.button_down or self.r_pinch.finger:
                if self.button_down:
                    self.mouse.up("left", *self.cursor)
                    self.button_down = False
                self.r_pinch.reset()
                self.zooming = False
            self.fx.reset()
            self.fy.reset()
            self.prec = None
            return
        lm, raw = right["lm"], right["raw"]
        frozen = right["pose"] in ("fist", "call")   # cursor stays put while you dictate
        blocked = right["shape"] in ("fist", "thumbs_up", "thumbs_down")
        started, ended = self.r_pinch.update(right["ratios"], blocked, t)
        finger = self.r_pinch.finger
        info = {"pose": right["pose"], "pinch": finger,
                "mode": "dictate" if right["pose"] == "call" else "point"}
        st["right"] = info

        # Cursor anchor: between the index and middle knuckles. Unlike a
        # fingertip it barely moves when you pinch, so clicks land on target.
        ax = (raw[INDEX_MCP][0] + raw[MIDDLE_MCP][0]) / 2
        ay = (raw[INDEX_MCP][1] + raw[MIDDLE_MCP][1]) / 2
        target = self._map((ax, ay))

        precision = bool(left and left.get("pose") == "fist" and not frozen)
        if precision:
            info["mode"] = "precision"
            if self.prec is None:
                self.prec = (target, self.cursor)
            (a0x, a0y), (c0x, c0y) = self.prec
            g = c["precision_gain"]
            goal = (c0x + (target[0] - a0x) * g, c0y + (target[1] - a0y) * g)
        else:
            if self.prec is not None:     # leaving precision: glide back, no jump
                self.offset = (self.cursor[0] - target[0], self.cursor[1] - target[1])
                self.prec = None
                self.fx.reset()
                self.fy.reset()
            k = math.exp(-dt * 2.5)
            self.offset = (self.offset[0] * k, self.offset[1] * k)
            goal = (target[0] + self.offset[0], target[1] + self.offset[1])
        goal = self._clamp(*goal)
        sx, sy = self.fx(goal[0], t), self.fy(goal[1], t)

        # Two-hand zoom: left index pinch already held when right index pinches.
        if started == "index" and self.l_pinch.finger == "index":
            self.zooming, self.zoom_base = True, None
        if self.zooming:
            info["mode"] = "zoom"
            if finger != "index" or self.l_pinch.finger != "index":
                self.zooming = False
                return
            d = dist(_pinch_point(left["lm"]), _pinch_point(lm))
            if self.zoom_base is None:
                self.zoom_base = d
            elif d > self.zoom_base * c["zoom_step"]:
                self.do("zoom_in", st)
                self.zoom_base = d
            elif d < self.zoom_base / c["zoom_step"]:
                self.do("zoom_out", st)
                self.zoom_base = d
            return

        if started:
            self.last_pinch_t = t
        settling = (t - self.last_pinch_t) < c["click_settle_s"]
        if frozen:
            info["mode"] = "freeze"
        elif not settling:
            self.cursor = (sx, sy)
            self.mouse.move(sx, sy)

        if started == "index":
            near = dist(self.cursor, self.last_up_pos) < c["double_click_px"]
            if t - self.last_up_t < c["double_click_s"] and near:
                self.click_count = min(3, self.click_count + 1)
            else:
                self.click_count = 1
            self.mouse.down("left", *self.cursor, clicks=self.click_count)
            self.button_down = True
            st["event"] = ["click", "double click", "triple click"][self.click_count - 1]
        elif ended == "index" and self.button_down:
            self.mouse.up("left", *self.cursor, clicks=self.click_count)
            self.button_down = False
            self.last_up_t, self.last_up_pos = t, self.cursor
        if self.button_down:
            info["mode"] = "drag / select"
        if started in ("middle", "ring", "pinky"):
            self._bound(f"right.{started}.pinch", st)
        if finger in ("middle", "ring", "pinky"):
            info["mode"] = label_for(self.bindings.get(f"right.{finger}.pinch", finger))

    def _inertia(self, dt):
        if self.l_pinch.finger == "index" or self.zooming:
            return
        vx, vy = self.scroll_vel
        if abs(vx) + abs(vy) < 40:
            self.scroll_vel = (0.0, 0.0)
            return
        self.mouse.scroll(vx * dt, vy * dt)
        k = math.exp(-dt * 4.0)
        self.scroll_vel = (vx * k, vy * k)


def _pinch_point(lm):
    return ((lm[THUMB_TIP][0] + lm[INDEX_TIP][0]) / 2,
            (lm[THUMB_TIP][1] + lm[INDEX_TIP][1]) / 2)


def cheat_sheet(bindings=None):
    """Lines for the on-screen help, built from the live bindings."""
    b = dict(DEFAULT_BINDINGS)
    b.update(bindings or {})
    names = {"open": "open palm", "peace": "peace sign", "three": "three fingers",
             "point": "pointing", "thumbs_down": "thumbs down", "thumbs_up": "thumbs up"}
    lines = [("RIGHT HAND", "the mouse"),
             ("move hand", "move cursor"),
             ("pinch index", "click · hold to drag/select · 2x = double click"),
             ("fist", "freeze cursor")]
    for f in ("middle", "ring", "pinky"):
        if b.get(f"right.{f}.pinch"):
            lines.append((f"pinch {f}", label_for(b[f"right.{f}.pinch"])))
    lines += [("LEFT HAND", "shortcuts"), ("pinch index + move", "scroll")]
    for f in ("middle", "ring", "pinky"):
        tap, hold = b.get(f"left.{f}.tap"), b.get(f"left.{f}.hold")
        if tap or hold:
            s = label_for(tap) if tap else ""
            if hold:
                s += f" · hold: {label_for(hold)}"
            lines.append((f"tap {f}", s))
    for pose in ("open", "peace", "three", "point", "thumbs_down"):
        sw = [(d, b.get(f"left.{pose}.swipe_{d}")) for d in ("left", "right", "up", "down")]
        sw = [f"{'←→↑↓'[('left', 'right', 'up', 'down').index(d)]} {label_for(a)}"
              for d, a in sw if a]
        hold = b.get(f"left.{pose}.hold")
        parts = (["swipe " + ", ".join(sw)] if sw else []) + (
            [f"hold: {label_for(hold)}"] if hold else [])
        if parts:
            lines.append((names[pose], " · ".join(parts)))
    lines += [("thumbs up + slide", "app switcher (⌘-Tab)"),
              ("fist", "precision cursor")]
    lines += [("EITHER HAND", ""), ("call-me sign (thumb+pinky)", "dictate with Wispr Flow")]
    lines += [("BOTH HANDS", "")]
    if b.get("both.open.hold"):
        lines.append(("both palms, hold", label_for(b["both.open.hold"])))
    lines += [("left pinch + right pinch", "spread / squeeze to zoom"),
              ("both fists, hold", "pause / resume")]
    return lines
