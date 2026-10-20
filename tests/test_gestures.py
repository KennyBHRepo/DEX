"""Synthetic-hand tests for every gesture. Run: python tests/test_gestures.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from gestures import Engine, classify, pinch_ratios
from backends import DryRun

FING = {"index": (5, -0.35), "middle": (9, -0.12), "ring": (13, 0.10), "pinky": (17, 0.30)}

def hand(cx, cy, pose="open", s=0.12):
    """Upright synthetic hand, wrist at (cx, cy). pose: open, fist, point, peace,
    three, thumbs_up, thumbs_down, pinch_<finger>."""
    ext = {"open": "imrp", "point": "i", "peace": "im", "three": "imr", "call": "p"}.get(pose, "imrp")
    if pose in ("fist", "thumbs_up", "thumbs_down"):
        ext = ""
    lm = [None] * 21
    lm[0] = (cx, cy)
    for name, (mcp, dx) in FING.items():
        bx, by = cx + dx * s, cy - 0.9 * s
        lm[mcp] = (bx, by)
        if name[0] in ext:
            lm[mcp + 1], lm[mcp + 2], lm[mcp + 3] = (bx, by - .4 * s), (bx, by - .65 * s), (bx, by - .85 * s)
        else:
            lm[mcp + 1], lm[mcp + 2], lm[mcp + 3] = (bx, by - .3 * s), (bx, by - .1 * s), (bx, by + .15 * s)
    lm[1], lm[2], lm[3], lm[4] = (cx - .3*s, cy - .2*s), (cx - .55*s, cy - .4*s), (cx - .75*s, cy - .55*s), (cx - .95*s, cy - .7*s)
    if pose == "fist":
        lm[3], lm[4] = (cx - .5*s, cy - .5*s), (cx - .3*s, cy - .6*s)
    if pose == "thumbs_up":
        lm[2], lm[3], lm[4] = (cx - .45*s, cy - .6*s), (cx - .5*s, cy - 1.0*s), (cx - .55*s, cy - 1.4*s)
    if pose == "call":
        lm[2], lm[3], lm[4] = (cx - .5*s, cy - .5*s), (cx - .8*s, cy - .7*s), (cx - 1.1*s, cy - .85*s)
    if pose == "thumbs_down":
        lm[2], lm[3], lm[4] = (cx - .45*s, cy - .2*s), (cx - .5*s, cy + .3*s), (cx - .55*s, cy + .7*s)
    if pose.startswith("pinch_"):
        tip = {"index": 8, "middle": 12, "ring": 16, "pinky": 20}[pose[6:]]
        lm[4] = lm[tip]
    return lm

R = lambda lm: {"label": "Right", "lm": lm}
L = lambda lm: {"label": "Left", "lm": lm}
log = []
b = DryRun(log)
e = Engine(b, b, 1440, 900)
t = 0.0
def step(hands, n=1, dt=1/30):
    global t
    st = None
    for _ in range(n):
        t += dt
        st = e.update(hands, t, aspect=1.0)
    return st
def acts():
    return [x for x in log if x[0] not in ("move", "scroll")]
def rest(n=20):
    step([], n); log.clear()
fails = []
def check(name, cond, got):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"   got: {got}"))
    if not cond: fails.append(name)

# --- poses
for p in ("open", "fist", "point", "peace", "three", "call", "thumbs_up", "thumbs_down"):
    check(f"classify {p}", classify(hand(.5, .6, p)) == p, classify(hand(.5, .6, p)))
for f in ("index", "middle", "ring", "pinky"):
    r = pinch_ratios(hand(.5, .6, "pinch_" + f))
    check(f"pinch detect {f}", min(r, key=r.get) == f and r[f] < 0.3, r)

# --- right hand: the mouse
step([R(hand(.3, .5))], 10); step([R(hand(.7, .6))], 20)
mv = [x for x in log if x[0] == "move"]
check("cursor follows hand", mv[-1][1] > mv[0][1] + 500, (mv[0], mv[-1]))
log.clear(); step([R(hand(.7, .6, "pinch_index"))], 3); step([R(hand(.7, .6))], 3)
check("click", acts() == [("down", "left", 1), ("up", "left", 1)], acts())
log.clear(); step([R(hand(.7, .6, "pinch_index"))], 3); step([R(hand(.7, .6))], 3)
check("double click", acts() == [("down", "left", 2), ("up", "left", 2)], acts())
step([R(hand(.7, .6))], 20); log.clear()
step([R(hand(.4, .5, "pinch_index"))], 6)
for k in range(10): step([R(hand(.4 + k * .02, .5, "pinch_index"))])
step([R(hand(.6, .5))], 3)
ev = [x[0] for x in log]
check("drag / select", "down" in ev and ev[ev.index("down") + 1:].count("move") >= 8 and "up" in ev and ev.count("move") >= 8, ev)
rest()
step([R(hand(.6, .5))], 5); log.clear(); step([R(hand(.6, .5, "pinch_middle"))], 3); step([R(hand(.6, .5))], 3)
check("right click", acts() == [("click", "right")], acts())
log.clear(); step([R(hand(.6, .5, "pinch_ring"))], 3); step([R(hand(.6, .5))], 3)
check("cmd-click (new tab)", acts() == [("click", "left", "cmd")], acts())
log.clear(); step([R(hand(.6, .5, "pinch_pinky"))], 3); step([R(hand(.6, .5))], 3)
check("shift-click (extend selection)", acts() == [("click", "left", "shift")], acts())
log.clear(); step([R(hand(.6, .5, "fist"))], 10)
check("fist freezes cursor, no click", acts() == [] and len(log) <= 4, log)
rest()

# --- precision mode
step([R(hand(.5, .5))], 15); log.clear()
step([L(hand(.2, .6, "fist")), R(hand(.5, .5))], 6); x0 = e.cursor[0]; log.clear()
step([L(hand(.2, .6, "fist")), R(hand(.6, .5))], 30)
full = 0.1 / 0.64 * 1440
check("precision: cursor moves 1/4 as far", abs((e.cursor[0] - x0) - full * 0.25) < 15, (x0, e.cursor[0]))
x1 = e.cursor[0]; log.clear(); step([L(hand(.2, .6)), R(hand(.6, .5))], 2)
check("leaving precision doesn't jump", abs(e.cursor[0] - x1) < 40, (x1, e.cursor[0]))
step([L(hand(.2, .6)), R(hand(.6, .5))], 60)
check("...then glides back to where the hand points", abs(e.cursor[0] - (x0 + full)) < 25, e.cursor)
rest()

# --- left hand: shortcuts
step([L(hand(.3, .7, "pinch_index"))], 3)
for k in range(8): step([L(hand(.3, .7 - k * .02, "pinch_index"))])
sc = [x for x in log if x[0] == "scroll"]
check("scroll (pinch + move up)", len(sc) >= 6 and all(x[2] < 0 for x in sc), sc[:3])
log.clear(); step([L(hand(.3, .5))], 10)
check("scroll momentum after release", len([x for x in log if x[0] == "scroll"]) >= 3, log)
rest()
for f, tap, hold in (("middle", "c", "x"), ("ring", "v", "v"), ("pinky", "z", "z")):
    step([L(hand(.3, .5))], 5); log.clear()
    step([L(hand(.3, .5, "pinch_" + f))], 4); step([L(hand(.3, .5))], 3)
    check(f"left {f} tap", acts() and acts()[-1][-1] == tap and len(acts()) == 1, acts())
    log.clear(); step([L(hand(.3, .5, "pinch_" + f))], 25); step([L(hand(.3, .5))], 3)
    a = acts()
    check(f"left {f} hold", len(a) == 1 and a[0][-1] == hold and a[0] != ("hotkey", "cmd", tap) or f == "ring" and a == [("hotkey", "cmd", "alt", "shift", "v")] or f == "pinky" and a == [("hotkey", "cmd", "shift", "z")], a)
    rest()

def swipe(pose, dx=0.0, dy=0.0, frames=6):
    step([L(hand(.5, .55, pose))], 8); log.clear()
    for k in range(1, frames + 1):
        step([L(hand(.5 + dx * k / frames, .55 + dy * k / frames, pose))])
    a = acts(); rest(); return a
check("open palm swipe left = next tab", swipe("open", -.3) == [("hotkey", "ctrl", "tab")], None)
check("open palm swipe right = previous tab", swipe("open", .3) == [("hotkey", "ctrl", "shift", "tab")], None)
check("peace swipe right = back", swipe("peace", .3) == [("hotkey", "cmd", "[")], None)
check("peace swipe left = forward", swipe("peace", -.3) == [("hotkey", "cmd", "]")], None)
check("three fingers swipe left = next desktop", swipe("three", -.3) == [("hotkey", "ctrl", "right")], None)
check("three fingers swipe up = Mission Control", swipe("three", 0, -.3) == [("hotkey", "ctrl", "up")], None)
check("three fingers swipe down = App Expose", swipe("three", 0, .3) == [("hotkey", "ctrl", "down")], None)
check("slow drift is not a swipe", swipe("open", -.15, frames=40) == [], None)
step([L(hand(.2, .5))], 8); log.clear(); step([L(hand(.7, .5))], 6)
check("tracking jump is not a swipe", acts() == [], acts()); rest()
step([L(hand(.4, .5, "point"))], 25)
check("point hold = new tab", acts() == [("hotkey", "cmd", "t")], acts()); rest()
step([L(hand(.4, .5, "thumbs_down"))], 25)
check("thumbs down hold = close tab", acts() == [("hotkey", "cmd", "w")], acts()); rest()
step([L(hand(.4, .5, "thumbs_up"))], 6)
for k in range(1, 9): step([L(hand(.4 + k * .025, .5, "thumbs_up"))])
step([L(hand(.6, .5))], 6)
a = acts()
check("thumbs up = app switcher, slide picks, release switches",
      a[0] == ("mod_down", "cmd") and a.count(("hotkey", "cmd", "tab")) >= 2 and a[-1] == ("mod_up", "cmd"), a)
rest()

# --- both hands
step([L(hand(.3, .5)), R(hand(.7, .5))], 25)
check("both palms hold = Spotlight", acts() == [("hotkey", "cmd", "space")], acts()); rest()
step([L(hand(.4, .6, "pinch_index")), R(hand(.6, .6))], 4)
step([L(hand(.4, .6, "pinch_index")), R(hand(.6, .6, "pinch_index"))], 4)
for k in range(10): step([L(hand(.4 - k * .02, .6, "pinch_index")), R(hand(.6 + k * .02, .6, "pinch_index"))])
a = acts()
check("two-hand spread = zoom in, no click", a and all(x == ("hotkey", "cmd", "=") for x in a), a); rest()
st = step([L(hand(.3, .5, "fist")), R(hand(.7, .5, "fist"))], 40)
check("both fists hold = pause", st["paused"], st)
log.clear(); step([R(hand(.2, .2))], 10); step([R(hand(.2, .2, "pinch_index"))], 5)
check("nothing happens while paused", log == [], log)
step([], 3); st = step([L(hand(.3, .5, "fist")), R(hand(.7, .5, "fist"))], 40)
check("both fists again = resume", not st["paused"], st); rest()
step([R(hand(.5, .5, "pinch_index"))], 5); step([], 2)
check("hand leaves mid-drag -> button released", acts() == [("down", "left", 1), ("up", "left", 1)], acts())
step([L(hand(.4, .5, "thumbs_up"))], 6); step([], 2)
check("hand leaves app switcher -> Cmd released", acts()[-1] == ("mod_up", "cmd"), acts())

# --- dictation (Wispr Flow)
rest()
step([L(hand(.3, .5))], 5); log.clear()
step([L(hand(.3, .5, "call"))], 10)
check("call-me sign holds Fn (push to talk)", acts() == [("hold", "fn", True)], acts())
step([L(hand(.3, .5))], 2); step([L(hand(.3, .5, "call"))], 10)
check("brief flicker doesn't stop dictation", acts() == [("hold", "fn", True)], acts())
step([L(hand(.3, .5))], 25)
check("dropping the sign releases Fn", acts() == [("hold", "fn", True), ("hold", "fn", False)], acts())
rest()
step([R(hand(.6, .5))], 10); log.clear(); step([R(hand(.6, .5, "call"))], 10)
check("works with the right hand too, cursor stays put",
      acts() == [("hold", "fn", True)] and len([x for x in log if x[0] == "move"]) <= 3, log)
step([], 30)
check("hand leaves frame -> Fn released", acts()[-1] == ("hold", "fn", False), acts()); rest()
step([L(hand(.3, .5, "call"))], 10)
step([L(hand(.3, .5, "fist")), R(hand(.7, .5, "fist"))], 40)
check("pausing releases Fn", ("hold", "fn", False) in acts(), acts())
step([], 3); step([L(hand(.3, .5, "fist")), R(hand(.7, .5, "fist"))], 40); rest()
e3 = Engine(b, b, 1440, 900, cfg={"dictation_mode": "hands_free"}); t3 = 0
def s3(hs, n):
    global t3
    for _ in range(n):
        t3 += 1/30; e3.update(hs, t3, 1.0)
s3([L(hand(.3, .5, "call"))], 8); s3([L(hand(.3, .5))], 25)
on = acts(); s3([L(hand(.3, .5, "call"))], 8); s3([L(hand(.3, .5))], 25)
check("hands-free: flash sign = Fn+Space on, again = off",
      on == [("hotkey", "fn", "space")] and acts() == [("hotkey", "fn", "space")] * 2 and not e3.dictating, acts())
rest()

# --- custom bindings
log.clear(); e2 = Engine(b, b, 1440, 900, bindings={"left.middle.tap": "cmd+shift+t", "left.middle.hold": None})
t2 = 0
for pose, n in (("open", 5), ("pinch_middle", 3)):
    for _ in range(n):
        t2 += 1/30; e2.update([L(hand(.3, .5, pose))], t2, 1.0)
check("custom binding fires instantly when no hold is bound", acts() == [("hotkey", "cmd", "shift", "t")], acts())

print(f"\n{len(fails)} failed" if fails else "\nALL PASSED")
sys.exit(1 if fails else 0)
