"""Settings persistence and validation; no camera or input permissions needed."""
import json
import pathlib
import sys
import tempfile
import unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from preferences import validate_settings, save_settings
from gestures import DEFAULTS

class SettingsTests(unittest.TestCase):
    def test_rejects_invalid_thresholds_and_nonfinite_values(self):
        for change in ({'pinch_press': .5, 'pinch_release': .4},
                       {'scroll_gain': float('nan')}, {'tap_hold_s': -1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_settings(dict(DEFAULTS, **change))

    def test_preserves_advanced_options_and_bindings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(pathlib.Path(folder) / 'config.json')
            original = {'bindings': {'left.middle.tap': 'cmd+shift+t'}, '_note': 'Keep', 'camera': 'auto'}
            pathlib.Path(path).write_text(json.dumps(original))
            updates = validate_settings(DEFAULTS)
            save_settings(path, updates)
            actual = json.loads(pathlib.Path(path).read_text())
            self.assertEqual(actual, dict(original, **updates))
            self.assertFalse(pathlib.Path(path + '.tmp').exists())

    def test_bad_json_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'config.json'
            path.write_text('{broken')
            with self.assertRaises(ValueError):
                save_settings(str(path), {'scroll_gain': 1000})
            self.assertEqual(path.read_text(), '{broken')

if __name__ == '__main__':
    unittest.main()
