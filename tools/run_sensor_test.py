import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
from tools.camera_debugger import connect

with connect() as dbg:
    dbg.request(3, b"/tmp_bt/patch_inh_factor > /tmp_bt/patch_inh.log 2>&1")
    patch_log, _ = dbg.read_all("/tmp_bt/patch_inh.log")
    print("Patch log:\n" + patch_log.decode("latin1", errors="replace"))

    dbg.request(3, b"/bin/sh -c '/tmp_bt/test_sensor_activate_and_acquire_arm > /tmp_bt/sensor_test.log 2>&1 &'")
    print("Waiting 4s for test execution...")
    time.sleep(4)
    log_data, _ = dbg.read_all("/tmp_bt/sensor_test.log")
    print("Sensor test output:\n" + log_data.decode("latin1", errors="replace"))
