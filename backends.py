"""OS control backends. macOS uses Quartz directly (real drag events, proper
double-click counts, pixel scrolling, modifier-clicks). Other systems fall
back to pynput."""
import sys

MAC_KEYS = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28,
    "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "return": 36,
    "enter": 36, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43,
    "/": 44, "n": 45, "m": 46, ".": 47, "tab": 48, "space": 49, "`": 50,
    "delete": 51, "backspace": 51, "esc": 53, "escape": 53,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98,
    "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "home": 115, "pageup": 116, "forwarddelete": 117, "end": 119, "pagedown": 121,
    "left": 123, "right": 124, "down": 125, "up": 126,
}
MAC_MOD_KEYS = {"cmd": 55, "shift": 56, "alt": 58, "ctrl": 59, "fn": 63}
ALIASES = {"command": "cmd", "option": "alt", "opt": "alt", "control": "ctrl",
           "globe": "fn"}


class DryRun:
    """Logs instead of controlling the computer. Used by --dry-run and tests."""

    def __init__(self, log=None):
        self.log = log if log is not None else []
        self.size = (1440, 900)

    def screen_size(self):
        return self.size

    def move(self, x, y):
        self.log.append(("move", round(x), round(y)))

    def down(self, b, x, y, clicks=1):
        self.log.append(("down", b, clicks))

    def up(self, b, x, y, clicks=1):
        self.log.append(("up", b, clicks))

    def click(self, b, x, y, mods=()):
        self.log.append(("click", b) + tuple(mods))

    def scroll(self, dx, dy):
        self.log.append(("scroll", round(dx), round(dy)))

    def hotkey(self, *keys):
        self.log.append(("hotkey",) + keys)

    def mod_down(self, m):
        self.log.append(("mod_down", m))

    def mod_up(self, m):
        self.log.append(("mod_up", m))

    def hold(self, combo, down):
        self.log.append(("hold", combo, down))


class MacBackend:
    def __init__(self):
        import Quartz as Q
        self.Q = Q
        self.buttons = {"left": False, "right": False}
        self.held = set()
        self.FLAGS = {"cmd": Q.kCGEventFlagMaskCommand, "shift": Q.kCGEventFlagMaskShift,
                      "alt": Q.kCGEventFlagMaskAlternate, "ctrl": Q.kCGEventFlagMaskControl,
                      "fn": Q.kCGEventFlagMaskSecondaryFn}

    def screen_size(self):
        from displays import active_rects, bounds
        self.display_rects = active_rects(self.Q)
        self.desktop_bounds = bounds(self.display_rects)
        return int(self.desktop_bounds[2]), int(self.desktop_bounds[3])

    def _flags(self, mods=()):
        f = 0
        for m in set(mods) | self.held:
            f |= self.FLAGS[m]
        return f

    def _mouse(self, etype, x, y, button, clicks=1, mods=()):
        Q = self.Q
        from displays import nearest_point
        if not hasattr(self, 'desktop_bounds'):
            self.screen_size()
        ox, oy, _, _ = self.desktop_bounds
        x, y = nearest_point(x + ox, y + oy, self.display_rects)
        e = Q.CGEventCreateMouseEvent(None, etype, (x, y), button)
        Q.CGEventSetIntegerValueField(e, Q.kCGMouseEventClickState, clicks)
        flags = self._flags(mods)
        if flags:
            Q.CGEventSetFlags(e, flags)
        Q.CGEventPost(Q.kCGHIDEventTap, e)

    def move(self, x, y):
        Q = self.Q
        if self.buttons["left"]:
            self._mouse(Q.kCGEventLeftMouseDragged, x, y, Q.kCGMouseButtonLeft)
        elif self.buttons["right"]:
            self._mouse(Q.kCGEventRightMouseDragged, x, y, Q.kCGMouseButtonRight)
        else:
            self._mouse(Q.kCGEventMouseMoved, x, y, Q.kCGMouseButtonLeft)

    def _btn(self, b, down, x, y, clicks=1, mods=()):
        Q = self.Q
        self.buttons[b] = down
        if b == "left":
            et = Q.kCGEventLeftMouseDown if down else Q.kCGEventLeftMouseUp
            self._mouse(et, x, y, Q.kCGMouseButtonLeft, clicks, mods)
        else:
            et = Q.kCGEventRightMouseDown if down else Q.kCGEventRightMouseUp
            self._mouse(et, x, y, Q.kCGMouseButtonRight, clicks, mods)

    def down(self, b, x, y, clicks=1):
        self._btn(b, True, x, y, clicks)

    def up(self, b, x, y, clicks=1):
        self._btn(b, False, x, y, clicks)

    def click(self, b, x, y, mods=()):
        for m in mods:
            self._key(MAC_MOD_KEYS[m], True, mods)
        self._btn(b, True, x, y, 1, mods)
        self._btn(b, False, x, y, 1, mods)
        for m in reversed(mods):
            self._key(MAC_MOD_KEYS[m], False, ())

    def scroll(self, dx, dy):
        Q = self.Q
        e = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitPixel, 2,
                                            int(round(dy)), int(round(dx)))
        Q.CGEventPost(Q.kCGHIDEventTap, e)

    def _key(self, code, down, mods):
        Q = self.Q
        e = Q.CGEventCreateKeyboardEvent(None, code, down)
        if code in MAC_MOD_KEYS.values():
            # A real keyboard reports modifier keys (incl. Fn/globe) as FlagsChanged.
            Q.CGEventSetType(e, Q.kCGEventFlagsChanged)
        Q.CGEventSetFlags(e, self._flags(mods))
        Q.CGEventPost(Q.kCGHIDEventTap, e)

    def hotkey(self, *keys):
        keys = [ALIASES.get(k, k) for k in keys]
        mods = [k for k in keys if k in MAC_MOD_KEYS]
        main = [k for k in keys if k not in MAC_MOD_KEYS]
        new_mods = [m for m in mods if m not in self.held]
        pressed = []
        for m in new_mods:                      # press modifiers like a person would
            pressed.append(m)
            self._key(MAC_MOD_KEYS[m], True, pressed)
        for k in main:
            self._key(MAC_KEYS[k], True, mods)
            self._key(MAC_KEYS[k], False, mods)
        for m in reversed(new_mods):
            pressed.remove(m)
            self._key(MAC_MOD_KEYS[m], False, pressed)

    def mod_down(self, m):
        self.held.add(m)
        self._key(MAC_MOD_KEYS[m], True, ())

    def mod_up(self, m):
        self.held.discard(m)
        self._key(MAC_MOD_KEYS[m], False, ())

    def hold(self, combo, down):
        """Press and keep holding a key or combo (e.g. Fn for Wispr push-to-talk)."""
        keys = [ALIASES.get(k, k) for k in combo.lower().split("+")]
        mods = [k for k in keys if k in MAC_MOD_KEYS]
        main = [k for k in keys if k not in MAC_MOD_KEYS]
        if down:
            for m in mods:
                self.mod_down(m)
            for k in main:
                self._key(MAC_KEYS[k], True, ())
        else:
            for k in reversed(main):
                self._key(MAC_KEYS[k], False, ())
            for m in reversed(mods):
                self.mod_up(m)


class PynputBackend:
    def __init__(self):
        from pynput.mouse import Controller as M, Button
        from pynput.keyboard import Controller as K, Key
        self.m, self.k, self.B, self.Key = M(), K(), Button, Key
        self.names = {"ctrl": Key.ctrl, "cmd": Key.ctrl if sys.platform == "win32" else Key.cmd,
                      "alt": Key.alt, "shift": Key.shift, "up": Key.up, "down": Key.down,
                      "left": Key.left, "right": Key.right, "tab": Key.tab,
                      "space": Key.space, "return": Key.enter, "esc": Key.esc,
                      "pageup": Key.page_up, "pagedown": Key.page_down}

    def screen_size(self):
        try:
            import tkinter
            r = tkinter.Tk()
            r.withdraw()
            s = r.winfo_screenwidth(), r.winfo_screenheight()
            r.destroy()
            return s
        except Exception:
            return 1920, 1080

    def move(self, x, y):
        self.m.position = (int(x), int(y))

    def down(self, b, x, y, clicks=1):
        self.m.press(getattr(self.B, b))

    def up(self, b, x, y, clicks=1):
        self.m.release(getattr(self.B, b))

    def click(self, b, x, y, mods=()):
        ks = [self.names[ALIASES.get(m, m)] for m in mods]
        for k in ks:
            self.k.press(k)
        self.m.click(getattr(self.B, b))
        for k in reversed(ks):
            self.k.release(k)

    def scroll(self, dx, dy):
        self.m.scroll(dx / 40, dy / 40)

    def hotkey(self, *keys):
        ks = [self.names.get(ALIASES.get(k, k), k) for k in keys]
        for k in ks:
            self.k.press(k)
        for k in reversed(ks):
            self.k.release(k)

    def mod_down(self, m):
        self.k.press(self.names[m])

    def mod_up(self, m):
        self.k.release(self.names[m])

    def hold(self, combo, down):
        ks = [self.names.get(ALIASES.get(k, k), k) for k in combo.lower().split("+")]
        for k in (ks if down else reversed(ks)):
            (self.k.press if down else self.k.release)(k)


def make_backend(dry_run=False):
    if dry_run:
        return DryRun()
    if sys.platform == "darwin":
        return MacBackend()
    return PynputBackend()
