import json
import math
import os

FIELDS = [
    ('pinch_press', 'Pinch sensitivity', 0.05, 0.8),
    ('pinch_release', 'Pinch release threshold', 0.06, 1.0),
    ('smoothing_min_cutoff', 'Cursor responsiveness', 0.1, 10),
    ('scroll_gain', 'Scroll speed', 100, 6000),
    ('tap_hold_s', 'Shortcut hold time (seconds)', 0.2, 2),
]


def validate_settings(values):
    result = {}
    for key, label, low, high in FIELDS:
        value = float(values[key])
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{label} must be between {low} and {high}.')
        result[key] = value
    if result['pinch_release'] <= result['pinch_press']:
        raise ValueError('Release threshold must be larger than pinch sensitivity.')
    return result


def save_settings(path, updates):
    # Preserve custom bindings and all advanced options; replace atomically.
    with open(path, encoding='utf-8') as source:
        raw = json.load(source)
    raw.update(updates)
    temporary = path + '.tmp'
    try:
        with open(temporary, 'w', encoding='utf-8') as target:
            json.dump(raw, target, indent=2, ensure_ascii=False)
            target.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

