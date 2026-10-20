"""Hand intent gate based on tracking continuity and deliberate open-palm arming."""
import math
from gestures import classify

class GestureGuard:
    def __init__(self):
        self.states = {}
        self.reason = ''

    def filter(self, hands, now, faces=(), aspect=4/3):
        # faces is retained for compatibility; 2-D overlap cannot establish contact.
        accepted = []
        self.reason = ''
        seen = set()
        for hand in hands:
            key = hand['label']; seen.add(key)
            lm = hand['lm']
            center = tuple(sum(lm[i][a] for i in (0,5,9,13,17))/5 for a in (0,1))
            state = self.states.setdefault(key, dict(armed=False, since=None, last=now, center=center))
            jump = math.dist(center,state['center']) > .20
            lost = now-state['last'] > .18
            if jump or lost:
                state.update(armed=False,since=None)
            state.update(last=now,center=center)
            if jump:
                self.reason = 'Hold your hand steady'
                continue
            if not state['armed']:
                if classify([(x*aspect,y) for x,y in lm]) == 'open':
                    if state['since'] is None: state['since']=now
                    state['armed'] = now-state['since'] >= .35
                else:
                    state['since']=None
                if not state['armed']:
                    self.reason='Show an open palm to resume'
                    continue
            accepted.append(hand)
        for key in set(self.states)-seen:
            # A lost hand cannot return mid-pinch and fire a click.
            self.states[key].update(armed=False,since=None)
        return accepted
