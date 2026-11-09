import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import time
from tools.camera_debugger import connect

with connect() as dbg:
    with open('tools/native_camera/uvc_acquire_single_jpeg_arm', 'rb') as f:
        data = f.read()
    dbg.push('/tmp_bt/uvc_acquire_single_jpeg', data)
    dbg.request(3, b'chmod +x /tmp_bt/uvc_acquire_single_jpeg')
    dbg.request(3, b'/bin/sh -c "/tmp_bt/uvc_acquire_single_jpeg > /tmp_bt/acquire_out.log 2>&1 &"')
    print('Started acquisition tool in background. Waiting 5s...')
    time.sleep(5)
    out, _ = dbg.read_all('/tmp_bt/acquire_out.log')
    print('OUTPUT:\n' + out.decode('latin1', errors='replace'))
