import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import time
from tools.camera_debugger import connect

with connect() as dbg:
    # Remove any existing stop_feeder flag
    dbg.request(3, b'rm -f /tmp_bt/stop_feeder /tmp_bt/feeder.log')
    # Start feeder in background
    dbg.request(3, b'/bin/sh -c "/tmp_bt/uvc_sensor_feeder_30fps > /tmp_bt/feeder.log 2>&1 &"')
    print('Started feeder in background, waiting 3s...')
    time.sleep(3)
    # Stop feeder
    dbg.request(3, b'touch /tmp_bt/stop_feeder')
    time.sleep(1)
    log, _ = dbg.read_all('/tmp_bt/feeder.log')
    print('Feeder log:\n' + log.decode('latin1', errors='replace'))
