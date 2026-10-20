"""STARK controls catalog: every gesture, the action it runs and the exact input
it sends. Pure logic (no AppKit), so the Controls screen is fully testable.
"""
import json
import os

from gestures import ACTIONS, DEFAULT_BINDINGS, DEFAULTS, MOUSE_ACTIONS
from backends import MAC_KEYS, MAC_MOD_KEYS, ALIASES

# ------------------------------------------------------------------ display
MOD_ORDER = ("ctrl", "alt", "shift", "cmd", "fn")
MOD_SYMBOL = {"ctrl": "⌃", "alt": "⌥", "shift": "⇧", "cmd": "⌘", "fn": "fn "}
KEY_SYMBOL = {"left": "←", "right": "→", "up": "↑", "down": "↓", "space": "Space",
              "tab": "Tab", "return": "Return", "enter": "Return", "esc": "Esc",
              "escape": "Esc", "delete": "Delete", "backspace": "Delete",
              "forwarddelete": "Fwd Delete", "pageup": "Page Up",
              "pagedown": "Page Down", "home": "Home", "end": "End", "-": "−"}
MOUSE_INPUT = {"right_click": "Right click", "cmd_click": "⌘ Click",
               "shift_click": "⇧ Click", "opt_click": "⌥ Click",
               "double_click": "Double click"}

# Actions offered in the picker, grouped like a game's settings menu.
ACTION_GROUPS = [
    ("Editing", ["copy", "cut", "paste", "paste_match_style", "undo", "redo",
                 "select_all", "find"]),
    ("Browser", ["next_tab", "prev_tab", "new_tab", "close_tab", "reopen_tab",
                 "back", "forward", "reload", "address_bar"]),
    ("Windows and desktops", ["next_desktop", "prev_desktop", "mission_control",
                              "app_expose", "next_window", "minimize", "spotlight",
                              "screenshot"]),
    ("Page", ["page_down", "page_up", "top", "bottom", "zoom_in", "zoom_out",
              "enter", "escape"]),
    ("Mouse", ["right_click", "cmd_click", "shift_click", "opt_click", "double_click"]),
]
ACTION_LABELS = {
    "copy": "Copy", "cut": "Cut", "paste": "Paste",
    "paste_match_style": "Paste without formatting", "undo": "Undo", "redo": "Redo",
    "select_all": "Select all", "find": "Find", "next_tab": "Next tab",
    "prev_tab": "Previous tab", "new_tab": "New tab", "close_tab": "Close tab",
    "reopen_tab": "Reopen closed tab", "back": "Back", "forward": "Forward",
    "reload": "Reload page", "address_bar": "Go to address bar",
    "next_desktop": "Next desktop", "prev_desktop": "Previous desktop",
    "mission_control": "Mission Control", "app_expose": "App windows",
    "next_window": "Next window of app", "minimize": "Minimize window",
    "spotlight": "Spotlight search", "screenshot": "Screenshot area",
    "page_down": "Page down", "page_up": "Page up", "top": "Top of page",
    "bottom": "Bottom of page", "zoom_in": "Zoom in", "zoom_out": "Zoom out",
    "enter": "Return key", "escape": "Escape key", "right_click": "Right click",
    "cmd_click": "⌘-click (open in new tab)", "shift_click": "⇧-click (extend selection)",
    "opt_click": "⌥-click", "double_click": "Double click",
}

UNASSIGNED = None


def split_combo(combo):
    keys = [ALIASES.get(k, k) for k in str(combo).lower().split("+") if k]
    mods = [m for m in MOD_ORDER if m in keys]
    main = [k for k in keys if k not in MAC_MOD_KEYS]
    return mods, main


def format_combo(combo):
    """'ctrl+shift+tab' -> '⌃⇧Tab'. Modifier-only combos like 'fn' work too."""
    if not combo:
        return "—"
    mods, main = split_combo(combo)
    out = "".join(MOD_SYMBOL[m] for m in mods).strip() if not main else \
        "".join(MOD_SYMBOL[m] for m in mods)
    for k in main:
        out += KEY_SYMBOL.get(k, k.upper() if len(k) == 1 else k.title())
    return out.strip()


def input_for(action):
    """What STARK physically sends for an action name or raw combo."""
    if not action:
        return "—"
    if action in MOUSE_INPUT:
        return MOUSE_INPUT[action]
    return format_combo(ACTIONS.get(action, action))


def action_label(action):
    if not action:
        return "Not assigned"
    if action in ACTION_LABELS:
        return ACTION_LABELS[action]
    return "Custom shortcut"


def normalize_combo(combo):
    """Validate a combo and return it in canonical order, or raise ValueError."""
    if not combo or not str(combo).strip():
        raise ValueError("Press at least one key.")
    mods, main = split_combo(combo)
    unknown = [k for k in str(combo).lower().split("+")
               if ALIASES.get(k, k) not in MAC_KEYS and ALIASES.get(k, k) not in MAC_MOD_KEYS]
    if unknown:
        raise ValueError(f"STARK can't send {', '.join(unknown)}.")
    if len(main) > 1:
        raise ValueError("Use one main key plus modifiers.")
    return "+".join(mods + main)


def action_for_combo(combo):
    """Map a recorded combo back to a named action when one matches."""
    canonical = normalize_combo(combo)
    for name, keys in ACTIONS.items():
        try:
            if normalize_combo(keys) == canonical:
                return name
        except ValueError:
            continue
    return canonical


# ------------------------------------------------------------------ catalog
HANDS = {"right": "Right hand", "left": "Left hand", "both": "Both hands",
         "either": "Either hand", "app": "Keyboard"}
SHAPES = {"open": "Open palm", "peace": "Peace sign", "three": "Three fingers",
          "point": "Pointing finger", "thumbs_down": "Thumbs down"}
MOVES = {"swipe_left": "swipe left", "swipe_right": "swipe right",
         "swipe_up": "swipe up", "swipe_down": "swipe down", "hold": "hold still"}

# (category, binding key, gesture description, hand)
BINDABLE = (
    [("Pointer", f"right.{f}.pinch", f"Pinch thumb to {f}", "right")
     for f in ("middle", "ring", "pinky")]
    + [("Shortcuts", f"left.{f}.{m}", f"{'Tap' if m == 'tap' else 'Hold'} thumb to {f}", "left")
       for f in ("middle", "ring", "pinky") for m in ("tap", "hold")]
    + [("Hand shapes", f"left.{s}.{m}", f"{SHAPES[s]}, {MOVES[m]}", "left")
       for s in SHAPES for m in MOVES]
    + [("Both hands", "both.open.hold", "Both palms open, hold still", "both")]
)
BINDABLE_KEYS = [b[1] for b in BINDABLE]

# Built-in controls: shown so the list is complete, not remappable.
FIXED = [
    ("Pointer", "fixed.move", "Move your hand", "right", "Move pointer", "Mouse move"),
    ("Pointer", "fixed.click", "Pinch thumb to index", "right", "Click · hold to drag or select", "Left click"),
    ("Pointer", "fixed.double", "Pinch twice / three times fast", "right", "Double / triple click", "Double click"),
    ("Pointer", "fixed.freeze", "Make a fist", "right", "Freeze pointer", "—"),
    ("Shortcuts", "fixed.scroll", "Pinch thumb to index and move", "left", "Scroll, with momentum", "Scroll wheel"),
    ("Shortcuts", "fixed.precision", "Make a fist", "left", "Precision pointer (slow)", "—"),
    ("Shortcuts", "fixed.switcher", "Thumbs up, slide sideways", "left", "App switcher", "⌘Tab"),
    ("Both hands", "fixed.zoom", "Left index pinch, then right pinch, spread or squeeze", "both", "Zoom in / out", "⌘= / ⌘−"),
    ("Both hands", "fixed.stop", "Both fists, hold 1 second", "both", "Turn gestures off", "—"),
    ("Dictation", "fixed.dictate", "Call-me sign (thumb and pinky out)", "either", "Dictate with Wispr Flow", None),
    ("App", "fixed.toggle", "⌃⌥M from any app", "app", "Turn gestures on or off", "⌃⌥M"),
    ("App", "fixed.menubar", "STARK in the menu bar", "app", "Turn on/off, Controls, Settings", "Click"),
]
CATEGORIES = ["Pointer", "Shortcuts", "Hand shapes", "Both hands", "Dictation", "App"]


def catalog(bindings=None, cfg=None):
    """Every control as a row dict, in display order."""
    b = dict(DEFAULT_BINDINGS)
    b.update(bindings or {})
    c = dict(DEFAULTS)
    c.update(cfg or {})
    rows = []
    for category, key, gesture, hand, action, sent in FIXED:
        if key == "fixed.switcher" and not c.get("app_switcher", True):
            continue
        if key == "fixed.dictate":
            if not c.get("dictation", True):
                continue
            if c.get("dictation_mode") == "hands_free":
                gesture = "Call-me sign, flash to start / again to stop"
                sent = format_combo(c.get("dictation_hands_free_key", "fn+space"))
            else:
                sent = format_combo(c.get("dictation_key", "fn")) + " (held)"
        rows.append(dict(category=category, key=key, gesture=gesture, hand=HANDS[hand],
                         action=action, input=sent, editable=False, assigned=True))
    for category, key, gesture, hand in BINDABLE:
        a = b.get(key)
        rows.append(dict(category=category, key=key, gesture=gesture, hand=HANDS[hand],
                         action=action_label(a), input=input_for(a), editable=True,
                         assigned=bool(a), value=a, default=DEFAULT_BINDINGS.get(key)))
    order = {c: i for i, c in enumerate(CATEGORIES)}
    rows.sort(key=lambda r: (order[r["category"]], not r["assigned"] and r["editable"]))
    return rows


def search(rows, text):
    text = (text or "").strip().lower()
    if not text:
        return rows
    return [r for r in rows if any(text in str(r[f]).lower()
                                   for f in ("category", "gesture", "hand", "action", "input"))]


def changed_bindings(edited):
    """What to store in config.json: differences from the defaults only
    (None = a default the person turned off)."""
    out = {}
    for key in BINDABLE_KEYS:
        value = edited.get(key)
        if value != DEFAULT_BINDINGS.get(key):
            out[key] = value
    return out


def save_bindings(path, edited):
    """Write bindings into config.json, keeping every other setting. Atomic."""
    for key, value in edited.items():
        if key not in BINDABLE_KEYS:
            raise ValueError(f"Unknown control: {key}")
        if value and value not in ACTIONS and value not in MOUSE_ACTIONS:
            normalize_combo(value)
    with open(path, encoding="utf-8") as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as error:
            raise ValueError(f"config.json can't be read: {error}")
    keep = {k: v for k, v in raw.get("bindings", {}).items() if k.startswith("_")}
    keep.update(changed_bindings(edited))
    raw["bindings"] = keep
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ------------------------------------------------------------------ recorder
MAC_CODES = {}
for _name, _code in MAC_KEYS.items():
    MAC_CODES.setdefault(_code, _name)
# NSEvent modifier flag bits
FLAG_BITS = {"shift": 1 << 17, "ctrl": 1 << 18, "alt": 1 << 19, "cmd": 1 << 20, "fn": 1 << 23}
# Keys where macOS sets the fn flag on its own; it isn't really held.
IMPLICIT_FN = {"left", "right", "up", "down", "home", "end", "pageup", "pagedown",
               "forwarddelete", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9",
               "f10", "f11", "f12"}


def mods_from_flags(flags):
    return [m for m in MOD_ORDER if flags & FLAG_BITS[m]]


def combo_from_key(key_code, flags):
    """Turn a key press into a combo string, or None if the key isn't sendable."""
    key = MAC_CODES.get(int(key_code))
    if key is None:
        return None
    mods = mods_from_flags(int(flags))
    if key in IMPLICIT_FN and "fn" in mods:
        mods.remove("fn")
    return "+".join(mods + [key])


class Recorder:
    """Records one shortcut, game-style. Feed it key and modifier events.
    Esc cancels. Releasing modifiers with no key pressed records the modifiers
    alone (useful for a dictation key like fn or ⌃⌥)."""

    def __init__(self, allow_modifier_only=False):
        self.allow_modifier_only = allow_modifier_only
        self.peak = []
        self.result = None
        self.cancelled = False

    @property
    def done(self):
        return self.cancelled or self.result is not None

    def key_down(self, key_code, flags):
        if self.done:
            return
        key = MAC_CODES.get(int(key_code))
        mods = mods_from_flags(int(flags))
        if key in ("esc", "escape") and not mods:
            self.cancelled = True
            return
        combo = combo_from_key(key_code, flags)
        if combo:
            self.result = combo

    def flags_changed(self, flags):
        if self.done:
            return
        mods = mods_from_flags(int(flags))
        if len(mods) > len(self.peak):
            self.peak = mods
        if not mods and self.peak and self.allow_modifier_only:
            self.result = "+".join(self.peak)
