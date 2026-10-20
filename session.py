"""Explicit session states: off never runs the gesture engine.
No OS or UI dependencies; this is also the onboarding progress model.
"""
import math

STEPS = [
    ('Meet STARK.', 'Your hands are the interface. A few small movements move, click and scroll. Let’s run through them. Nothing here controls your Mac yet.', 'Let’s go', 'hand.wave.fill'),
    ('Show STARK your hand.', 'Raise your pointer hand at chest height, with your palm facing the camera. Keep your whole hand in the picture.', 'I can see my hand', 'hand.raised.fill'),
    ('Move a little.', 'Move your pointer hand slowly from side to side. The little dot in the camera follows you. Your real cursor stays put.', 'Next: try a click', 'cursorarrow.motionlines'),
    ('Pinch to click.', 'Touch the tip of your thumb to your index finger, then let go. That’s a click. Keep the other fingers relaxed.', 'Next: try scrolling', 'hand.pinch.fill'),
    ('A gentle scroll.', 'With your other hand, touch thumb to index finger. Keep them together and move your hand up or down.', 'Next: how to stop', 'arrow.up.and.down'),
    ('You’re in charge.', 'Use this button whenever you want STARK to stop. It switches off gestures and the camera. You can also use STARK in the menu bar or press ⌃⌥M.', 'Turn gestures off', 'pause.circle.fill'),
    ('That’s the idea.', 'You know the essentials. STARK stays off until you turn it on. Open Controls any time to see or remap every gesture.', 'Done', 'checkmark.seal.fill'),
]

class Session:
    def __init__(self, practice_only=False):
        self.mode = 'off'
        self.practice_only = practice_only
        self.suspended = False

    def set_mode(self, mode):
        if mode not in ('off', 'practice', 'control'):
            raise ValueError('Unknown session mode')
        if mode == 'control' and self.practice_only:
            mode = 'practice'
        self.mode = 'off' if self.suspended else mode

    def suspend(self, value):
        self.suspended = value
        self.mode = 'off'

    @property
    def recognizing(self):
        return self.mode != 'off' and not self.suspended

class Lesson:
    def __init__(self):
        self.reset(0)

    def reset(self, step):
        self.step = step
        self.complete = False
        self.origin = None
        self.seen_since = None

    def observe(self, data):
        if self.complete:
            return True
        pointer = data.get('pointer')
        if self.step == 1:
            if pointer is not None:
                now = data.get('time', 0)
                if self.seen_since is None:
                    self.seen_since = now
                self.complete = now - self.seen_since >= .5
            else:
                self.seen_since = None
        elif self.step == 2 and pointer is not None:
            if self.origin is None:
                self.origin = pointer
            self.complete = math.dist(self.origin, pointer) >= .16
        elif self.step == 3:
            self.complete = data.get('did_click', False)
        elif self.step == 4:
            self.complete = data.get('did_scroll', False)
        elif self.step == 5:
            self.complete = data.get('mode') == 'off'
        return self.complete
