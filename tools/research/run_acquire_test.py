import time
import os
from tools.camera_debugger import connect

def main():
    arm_bin_path = os.path.join(os.path.dirname(__file__), '..', 'native_camera', 'uvc_acquire_single_jpeg_arm')
    with open(arm_bin_path, 'rb') as f:
        bin_data = f.read()
    print(f"Loaded {len(bin_data)} bytes of uvc_acquire_single_jpeg_arm")

    with connect() as d:
        # 1. Push updated binary
        d.push('/tmp_bt/uvc_acquire_single_jpeg_arm', bin_data)
        d.request(3, b'chmod 755 /tmp_bt/uvc_acquire_single_jpeg_arm')
        d.request(3, b'rm -f /tmp_bt/acquire_run.log /tmp_bt/sensor_frame_720p.jpg')

        # 2. Launch background execution
        res = d.request(3, b'sh -c "/tmp_bt/uvc_acquire_single_jpeg_arm > /tmp_bt/acquire_run.log 2>&1 &"')
        print('LAUNCH STATUS:', res['status'], 'flags:', res['flags'])

        # 3. Monitor log
        for i in range(25):
            time.sleep(1)
            try:
                log, _ = d.read_all('/tmp_bt/acquire_run.log')
                txt = log.decode(errors='replace')
                print(f'--- T+{i+1}s ---')
                print(txt)
                if 'ACQUISITION EXECUTION FINISHED' in txt or 'FAIL:' in txt:
                    break
            except Exception as e:
                print(f'T+{i+1}s: {e}')

        # 4. Check for acquired frame
        try:
            stat_res = d.stat('/tmp_bt/sensor_frame_720p.jpg')
            size = stat_res.get('size', 0)
            print(f"sensor_frame_720p.jpg size on camera: {size}")
            if size > 0:
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
            print(f"Frame check: {e}")

        # 5. Check DMM state after test
        try:
            rule_data, _ = d.read_all('/proc/udm/dmm_rule')
            print(f"/proc/udm/dmm_rule: {rule_data.decode(errors='replace').strip()}")
        except Exception as e:
            print(f"dmm_rule check: {e}")

        try:
            units_data, _ = d.read_all('/proc/udm/dmm_units')
            print(f"/proc/udm/dmm_units:\n{units_data.decode(errors='replace').strip()}")
        except Exception as e:
            print(f"dmm_units check: {e}")

if __name__ == '__main__':
    main()
