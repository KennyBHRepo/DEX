"""One registered system-wide shortcut; does not monitor or record keystrokes."""
import ctypes as C

class HotKeyID(C.Structure):
    _fields_ = [('signature', C.c_uint32), ('id', C.c_uint32)]
class EventType(C.Structure):
    _fields_ = [('eventClass', C.c_uint32), ('eventKind', C.c_uint32)]

class GlobalShortcut:
    def __init__(self, callback):
        self.carbon = C.CDLL('/System/Library/Frameworks/Carbon.framework/Carbon')
        self.ref, self.handler = C.c_void_p(), C.c_void_p()
        self.callback_type = C.CFUNCTYPE(C.c_int32, C.c_void_p, C.c_void_p, C.c_void_p)
        self.callback = self.callback_type(lambda *_: self.invoke(callback))
        c = self.carbon
        c.GetApplicationEventTarget.restype = C.c_void_p
        c.InstallEventHandler.argtypes = [C.c_void_p, self.callback_type, C.c_uint32, C.POINTER(EventType), C.c_void_p, C.POINTER(C.c_void_p)]
        c.RegisterEventHotKey.argtypes = [C.c_uint32, C.c_uint32, HotKeyID, C.c_void_p, C.c_uint32, C.POINTER(C.c_void_p)]
        c.UnregisterEventHotKey.argtypes = [C.c_void_p]
        c.RemoveEventHandler.argtypes = [C.c_void_p]
        event = EventType(int.from_bytes(b'keyb','big'), 6)
        target = c.GetApplicationEventTarget()
        installed = c.InstallEventHandler(target, self.callback, 1, C.byref(event), None, C.byref(self.handler)) == 0
        self.available = installed and c.RegisterEventHotKey(46, (1 << 12) | (1 << 11), HotKeyID(int.from_bytes(b'STARK!','big'),1),target,0,C.byref(self.ref)) == 0

    @staticmethod
    def invoke(callback):
        try:
            callback()
        except Exception:
            import traceback
            traceback.print_exc()
        return 0

    def close(self):
        if self.ref:
            self.carbon.UnregisterEventHotKey(self.ref)
            self.ref = C.c_void_p()
        if self.handler:
            self.carbon.RemoveEventHandler(self.handler)
            self.handler = C.c_void_p()
