"""Controls screen logic: catalog, formatting, remapping, recording, saving."""
import json
import pathlib
import sys
import tempfile
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import controls as C
from gestures import DEFAULT_BINDINGS, Engine
from backends import DryRun

SHIFT, CTRL, ALT, CMD, FN = 1 << 17, 1 << 18, 1 << 19, 1 << 20, 1 << 23


class Formatting(unittest.TestCase):
    def test_symbols(self):
        self.assertEqual(C.format_combo("ctrl+shift+tab"), "⌃⇧Tab")
        self.assertEqual(C.format_combo("cmd+alt+shift+v"), "⌥⇧⌘V")
        self.assertEqual(C.format_combo("ctrl+up"), "⌃↑")
        self.assertEqual(C.format_combo("fn"), "fn")
        self.assertEqual(C.format_combo("ctrl+alt"), "⌃⌥")
        self.assertEqual(C.format_combo("cmd+-"), "⌘−")
        self.assertEqual(C.input_for("cmd_click"), "⌘ Click")
        self.assertEqual(C.input_for("copy"), "⌘C")
        self.assertEqual(C.input_for(None), "—")

    def test_normalize_and_reject(self):
        self.assertEqual(C.normalize_combo("shift+cmd+T"), "shift+cmd+t")
        self.assertEqual(C.normalize_combo("command+option+k"), "alt+cmd+k")
        for bad in ("", "cmd+hyper", "cmd+a+b"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                C.normalize_combo(bad)

    def test_recorded_combo_maps_to_named_action(self):
        self.assertEqual(C.action_for_combo("cmd+c"), "copy")
        self.assertEqual(C.action_for_combo("shift+ctrl+tab"), "prev_tab")
        self.assertEqual(C.action_for_combo("cmd+shift+k"), "shift+cmd+k")


class Catalog(unittest.TestCase):
    def test_every_default_and_builtin_is_listed(self):
        rows = C.catalog()
        keys = {r["key"] for r in rows}
        for k in DEFAULT_BINDINGS:
            self.assertIn(k, keys)
        for k in ("fixed.move", "fixed.click", "fixed.scroll", "fixed.dictate",
                  "fixed.toggle", "fixed.stop", "fixed.zoom", "fixed.switcher"):
            self.assertIn(k, keys)
        self.assertTrue(all(r["input"] for r in rows))

    def test_unassigned_slots_are_offered(self):
        rows = {r["key"]: r for r in C.catalog()}
        self.assertFalse(rows["left.open.hold"]["assigned"])
        self.assertEqual(rows["left.open.hold"]["action"], "Not assigned")
        self.assertTrue(rows["left.open.hold"]["editable"])

    def test_rows_reflect_custom_bindings_and_settings(self):
        rows = {r["key"]: r for r in C.catalog(
            {"left.middle.tap": "cmd+shift+t", "left.ring.tap": None},
            {"dictation_key": "ctrl+alt", "app_switcher": False})}
        self.assertEqual(rows["left.middle.tap"]["input"], "⇧⌘T")
        self.assertEqual(rows["left.middle.tap"]["action"], "Custom shortcut")
        self.assertFalse(rows["left.ring.tap"]["assigned"])
        self.assertEqual(rows["fixed.dictate"]["input"], "⌃⌥ (held)")
        self.assertNotIn("fixed.switcher", rows)

    def test_search(self):
        rows = C.catalog()
        self.assertTrue(all("tab" in (r["action"] + r["input"] + r["gesture"]).lower()
                            for r in C.search(rows, "tab")))
        self.assertEqual(C.search(rows, ""), rows)
        self.assertTrue(any(r["key"] == "left.middle.tap" for r in C.search(rows, "copy")))

    def test_every_bindable_key_is_one_the_engine_fires(self):
        # Fire each slot through the real gesture engine's binding lookup.
        log = []
        b = DryRun(log)
        for key in C.BINDABLE_KEYS:
            e = Engine(b, b, 100, 100, bindings={key: "cmd+k"})
            st = {}
            self.assertTrue(e._bound(key, st), key)
        self.assertEqual(len(log), len(C.BINDABLE_KEYS))


class Saving(unittest.TestCase):
    def test_only_changes_are_written_and_comments_kept(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(pathlib.Path(d) / "config.json")
            pathlib.Path(path).write_text(json.dumps(
                {"bindings": {"_how": "keep me", "left.middle.tap": "copy"}, "scroll_gain": 900}))
            edited = dict(DEFAULT_BINDINGS)
            edited.update({"left.open.hold": "reopen_tab", "left.pinky.hold": None,
                           "right.ring.pinch": "cmd+shift+k"})
            C.save_bindings(path, edited)
            raw = json.loads(pathlib.Path(path).read_text())
            self.assertEqual(raw["scroll_gain"], 900)
            self.assertEqual(raw["bindings"], {"_how": "keep me", "left.open.hold": "reopen_tab",
                                               "left.pinky.hold": None,
                                               "right.ring.pinch": "cmd+shift+k"})

    def test_bad_values_and_broken_files_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = pathlib.Path(d) / "config.json"
            path.write_text("{}")
            with self.assertRaises(ValueError):
                C.save_bindings(str(path), {"left.middle.tap": "cmd+hyper"})
            with self.assertRaises(ValueError):
                C.save_bindings(str(path), {"made.up": "copy"})
            path.write_text("{broken")
            with self.assertRaises(ValueError):
                C.save_bindings(str(path), {"left.middle.tap": "copy"})
            self.assertEqual(path.read_text(), "{broken")


class Recording(unittest.TestCase):
    def test_key_with_modifiers(self):
        r = C.Recorder()
        r.flags_changed(CMD)
        r.flags_changed(CMD | SHIFT)
        r.key_down(17, CMD | SHIFT)        # T
        self.assertEqual(r.result, "shift+cmd+t")

    def test_arrow_keys_drop_the_automatic_fn_flag(self):
        r = C.Recorder()
        r.key_down(126, CTRL | FN)         # ⌃↑ reports fn on its own
        self.assertEqual(r.result, "ctrl+up")

    def test_escape_cancels(self):
        r = C.Recorder()
        r.key_down(53, 0)
        self.assertTrue(r.cancelled and r.result is None)

    def test_modifier_only_for_dictation_key(self):
        r = C.Recorder(allow_modifier_only=True)
        r.flags_changed(FN)
        r.flags_changed(0)
        self.assertEqual(r.result, "fn")
        r = C.Recorder(allow_modifier_only=True)
        r.flags_changed(CTRL)
        r.flags_changed(CTRL | ALT)
        r.flags_changed(ALT)
        r.flags_changed(0)
        self.assertEqual(r.result, "ctrl+alt")
        r = C.Recorder()                   # gestures need a real key
        r.flags_changed(CMD)
        r.flags_changed(0)
        self.assertIsNone(r.result)


if __name__ == "__main__":
    unittest.main()
