"""Two short, separated transients wake STARK; audio is discarded in native code."""
import ctypes
from pathlib import Path

class DoubleClap:
    def __init__(self):
        self.noise=.008; self.started=None; self.first=None
        self.quiet_since=None; self.cool_until=0; self.last=None
        self.peak=0; self.crest=0

    def feed(self, t, peak, rms):
        if self.last is not None and (t-self.last > .2 or t < self.last):
            self.started=self.first=self.quiet_since=None
        self.last=t
        threshold=max(.12,self.noise*7)
        loud=peak>threshold and rms>max(.012,self.noise*2)
        if t < self.cool_until: return False
        if loud:
            if self.started is None:
                if self.quiet_since is None or t-self.quiet_since < .06: return False
                self.started=t; self.peak=peak; self.crest=peak/max(rms,.0001)
            self.peak=max(self.peak,peak); self.crest=max(self.crest,peak/max(rms,.0001))
            return False
        self.noise=.98*self.noise+.02*min(rms,.05)
        if self.started is not None:
            duration=t-self.started
            valid=.008 <= duration <= .12 and self.crest>=2.2
            start=self.started; self.started=None; self.quiet_since=t
            if valid:
                if self.first is not None and .18 <= start-self.first <= .65:
                    self.first=None; self.cool_until=t+2.5; return True
                self.first=start
            else: self.first=None
        elif self.quiet_since is None:
            self.quiet_since=t
        if self.first is not None and t-self.first > .65: self.first=None
        return False

class ClapListener:
    def __init__(self):
        import Foundation as F
        root=Path(str(F.NSBundle.mainBundle().resourcePath() or ''))
        path=root/'libDexAudio.dylib'
        if not path.is_file(): raise RuntimeError('Rebuild STARK.app to enable double-clap wake.')
        self.lib=ctypes.CDLL(str(path))
        self.lib.dex_audio_read.argtypes=[ctypes.POINTER(ctypes.c_double)]*3
        self.detector=DoubleClap()
        if not self.lib.dex_audio_start(): raise RuntimeError('Microphone unavailable. Check Microphone permission and your sound input.')

    def poll(self):
        if not self.lib.dex_audio_running(): raise RuntimeError('Microphone stopped. Turn double-clap wake off and on to reconnect.')
        triggered=False
        t=ctypes.c_double();p=ctypes.c_double();r=ctypes.c_double()
        for _ in range(256):
            if not self.lib.dex_audio_read(ctypes.byref(t),ctypes.byref(p),ctypes.byref(r)): break
            triggered=self.detector.feed(t.value,p.value,r.value) or triggered
        return triggered

    def close(self): self.lib.dex_audio_stop()
