import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from tools.camera_debugger import host_lock,ROOT


class DebuggerLockTests(unittest.TestCase):
    def test_other_process_is_excluded_and_lock_is_released(self):
        path=ROOT/'artifacts/tests'/('debug-lock-'+uuid.uuid4().hex)
        program='from tools.camera_debugger import host_lock; import sys;\ntry:\n with host_lock(sys.argv[1],.15): print("acquired")\nexcept TimeoutError: print("busy")'
        def child():
            return subprocess.run([sys.executable,'-c',program,str(path)],cwd=ROOT,
                                  capture_output=True,text=True,check=True).stdout.strip()
        try:
            with host_lock(path): self.assertEqual(child(),'busy')
            self.assertEqual(child(),'acquired')
        finally:
            path.unlink(missing_ok=True)


if __name__=='__main__': unittest.main()
