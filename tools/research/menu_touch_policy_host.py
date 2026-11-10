"""Host harness for explicit mod-policy tests, never a camera UI substitute."""
import ctypes as C
from functools import lru_cache
from pathlib import Path
import os
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[2]
class Event(C.Structure):
    _fields_=[('type',C.c_uint32),('mouse',C.c_uint8),('button',C.c_uint8)]
class Context(C.Structure):
    _fields_=[(x,C.c_uint32) for x in ('active','menu','page','generation','expected_tid','current_tid','rows','current_row','mouse')]
class State(C.Structure):
    _fields_=[(x,C.c_uint32) for x in ('armed','menu','page','generation','mouse','button','row')]
Position=C.CFUNCTYPE(C.c_int,C.c_void_p,C.c_uint,C.POINTER(C.c_int16),C.POINTER(C.c_int16))
Hit=C.CFUNCTYPE(C.c_int,C.c_void_p,C.c_uint,C.c_int16,C.c_int16)
Select=C.CFUNCTYPE(C.c_int,C.c_void_p,C.c_uint)
Refresh=C.CFUNCTYPE(None,C.c_void_p)
class Ops(C.Structure):
    _fields_=[('user',C.c_void_p),('position',Position),('hit',Hit),('select',Select),('refresh',Refresh)]
@lru_cache(maxsize=1)
def library():
    compiler=shutil.which('gcc') or shutil.which('cc')
    if not compiler: raise RuntimeError('Host C compiler unavailable')
    output=ROOT/'artifacts/analysis'/('menu_touch_policy_test.dll' if os.name=='nt' else 'menu_touch_policy_test.so')
    source=ROOT/'tools/native_camera/menu_touch_policy.c'
    if not (output.exists() and output.stat().st_mtime >= source.stat().st_mtime):
        subprocess.run([compiler,'-std=c11','-O2','-Wall','-Wextra','-Werror','-shared']+([] if os.name=='nt' else ['-fPIC'])+['-o',str(output),str(source)],check=True,capture_output=True)
    lib=C.CDLL(str(output));lib.mt_process.argtypes=[C.POINTER(State),C.POINTER(Context),C.POINTER(Event),C.POINTER(Ops)];lib.mt_process.restype=C.c_int
    lib.mt_decode.argtypes=[C.POINTER(C.c_uint8),C.c_uint,C.POINTER(Event)];lib.mt_decode.restype=C.c_int
    return lib
class Policy:
    def __init__(self,position,hit,select,refresh):
        self.errors=[]
        def guard(fn,default):
            def wrapped(*args):
                try:return fn(*args)
                except Exception as exc:self.errors.append(exc);return default
            return wrapped
        self.callbacks=(Position(guard(position,-1)),Hit(guard(hit,-1)),Select(guard(select,-1)),Refresh(guard(refresh,None)))
        self.ops=Ops(None,*self.callbacks);self.state=State();self.lib=library()
    def process(self,context,event):
        result=self.lib.mt_process(C.byref(self.state),C.byref(context),C.byref(event),C.byref(self.ops))
        if self.errors:raise self.errors.pop(0)
        return result
