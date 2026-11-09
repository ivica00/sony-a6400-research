import time
import os
import struct
from tools.camera_debugger import connect

def main():
    arm_bin_path = os.path.join(os.path.dirname(__file__), '..', 'native_camera', 'test_sensor_activate_and_acquire_arm')
    with open(arm_bin_path, 'rb') as f:
        bin_data = f.read()
    print(f"Loaded {len(bin_data)} bytes of test_sensor_activate_and_acquire_arm")

    with connect() as d:
        # 1. Preflight: check inh_tbl word 66
        tbl_addr = 0x05ac4008
        raw_tbl = d.memory(149, tbl_addr + 66 * 4, 4)
        w66_pre = struct.unpack('<I', raw_tbl)[0]
        print(f"Preflight inh_tbl word 66: 0x{w66_pre:08x} (bit 27 = {(w66_pre >> 27) & 1})")

        # 2. Push updated binary
        d.push('/tmp_bt/test_sensor_activate_and_acquire_arm', bin_data)
        d.request(3, b'chmod 755 /tmp_bt/test_sensor_activate_and_acquire_arm')
        d.request(3, b'rm -f /tmp_bt/sensor_test.log /tmp_bt/sensor_frame_720p.jpg')

        # 3. Launch execution
        print("Launching /tmp_bt/test_sensor_activate_and_acquire_arm...")
        res = d.request(3, b'sh -c "/tmp_bt/test_sensor_activate_and_acquire_arm > /tmp_bt/sensor_test.log 2>&1 &"')
        print('Launch status:', res['status'])

        # 4. Monitor execution log
        for i in range(25):
            time.sleep(1)
            try:
                log, _ = d.read_all('/tmp_bt/sensor_test.log')
                txt = log.decode(errors='replace')
                print(f"--- T+{i+1}s ---")
                lines = txt.strip().splitlines()
                for l in lines[-10:]:
                    print(" ", l)
                if '=== TEST FINISHED ===' in txt:
                    break
            except Exception as e:
                print(f"T+{i+1}s: {e}")

        # 5. Check inh_tbl word 66 post-test
        raw_tbl_post = d.memory(149, tbl_addr + 66 * 4, 4)
        w66_post = struct.unpack('<I', raw_tbl_post)[0]
        print(f"Post-test inh_tbl word 66: 0x{w66_post:08x} (bit 27 = {(w66_post >> 27) & 1})")

        # 6. Check for acquired frame
        res_ls = d.request(3, b'ls -l /tmp_bt/sensor_frame_720p.jpg 2>&1')
        print(f"Frame file check: {res_ls['payload'].decode(errors='replace').strip()}")
        if 'sensor_frame_720p.jpg' in res_ls['payload'].decode(errors='replace') and 'No such' not in res_ls['payload'].decode(errors='replace'):
            try:
                frame_data, _ = d.read_all('/tmp_bt/sensor_frame_720p.jpg')
                print(f"Downloaded {len(frame_data)} bytes of sensor_frame_720p.jpg")
                out_host = os.path.join(os.path.dirname(__file__), '..', '..', 'artifacts', 'sensor_frame_720p.jpg')
                os.makedirs(os.path.dirname(out_host), exist_ok=True)
                with open(out_host, 'wb') as f_out:
                    f_out.write(frame_data)
                print(f"Saved to {out_host}")
                if len(frame_data) >= 4:
                    print(f"SOI: {frame_data[:2].hex().upper()}, EOI: {frame_data[-2:].hex().upper()}")
            except Exception as e:
                print(f"Download error: {e}")

        # 7. Check DMM units cleanup
        res_units = d.request(3, b'cat /proc/udm/dmm_rule; cat /proc/udm/dmm_units')
        print("DMM STATUS POST-RUN:")
        print(res_units['payload'].decode(errors='replace')[:400])

if __name__ == '__main__':
    main()
