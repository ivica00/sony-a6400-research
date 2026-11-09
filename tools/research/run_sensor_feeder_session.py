import os
import time
from tools.camera_debugger import connect

def main():
    feeder_bin = os.path.join(os.path.dirname(__file__), '..', 'native_camera', 'uvc_sensor_feeder_30fps_arm')
    ko_path = os.path.join(os.path.dirname(__file__), '..', '..', 'artifacts', 'native', 'uvc-owned-dma-meta', 'usbg_video_a6400.ko')

    with open(feeder_bin, 'rb') as f:
        feeder_data = f.read()
    with open(ko_path, 'rb') as f:
        ko_data = f.read()

    print(f"Loaded feeder bin ({len(feeder_data)} bytes) and module ({len(ko_data)} bytes)")

    with connect() as d:
        # 1. Clean previous logs and stop signals
        d.request(3, b'rm -f /tmp_bt/feeder.log /tmp_bt/stop_feeder')

        # 2. Push files
        print("[*] Uploading feeder and kernel module to /tmp_bt...")
        d.push('/tmp_bt/uvc_sensor_feeder_30fps_arm', feeder_data)
        d.request(3, b'chmod 755 /tmp_bt/uvc_sensor_feeder_30fps_arm')
        d.push('/tmp_bt/usbg_video_a6400.ko', ko_data)

        # 3. Check / insert module
        kmods, _ = d.read_all('/proc/modules')
        if 'usbg_video_a6400' not in kmods.decode('latin1'):
            print("[*] Inserting usbg_video_a6400.ko...")
            res = d.request(3, b'insmod /tmp_bt/usbg_video_a6400.ko')
            print("    insmod status:", res['status'])
            d.request(3, b'mknod /tmp_bt/video c 248 33; chmod 666 /tmp_bt/video')
        else:
            print("[*] usbg_video_a6400.ko is already loaded.")

        # 4. Launch feeder in background
        print("[*] Launching uvc_sensor_feeder_30fps_arm...")
        res = d.request(3, b'sh -c "/tmp_bt/uvc_sensor_feeder_30fps_arm > /tmp_bt/feeder.log 2>&1 &"')
        print("    Launch status:", res['status'])

        # 5. Monitor feeder execution for 10 seconds
        stream_ok = False
        for sec in range(12):
            time.sleep(1)
            try:
                log_data, _ = d.read_all('/tmp_bt/feeder.log')
                txt = log_data.decode('latin1', errors='replace')
                print(f"--- T+{sec+1}s ---")
                lines = [l for l in txt.splitlines() if l.strip()]
                for l in lines[-6:]:
                    print("  ", l)
                if '30 FPS tick=' in txt:
                    stream_ok = True
                if 'TERMINATED' in txt or 'ERR' in txt:
                    break
                if sec >= 8 and stream_ok:
                    print("[*] Streaming active for >8s, issuing stop signal...")
                    d.request(3, b'touch /tmp_bt/stop_feeder')
            except Exception as e:
                print(f"Read error at T+{sec+1}s: {e}")

        # 6. Wait for teardown
        time.sleep(2)
        try:
            log_data, _ = d.read_all('/tmp_bt/feeder.log')
            print("\n=== FINAL FEEDER LOG ===")
            print(log_data.decode('latin1', errors='replace'))
        except Exception as e:
            print("Could not read final log:", e)

        # 7. Unload module
        print("[*] Unloading usbg_video_a6400.ko...")
        d.request(3, b'rmmod usbg_video_a6400')

        # 8. Check DMM state
        rule, _ = d.read_all('/proc/udm/dmm_rule')
        print("[*] Post-run DMM Rule:", rule.decode('latin1').strip())
        units, _ = d.read_all('/proc/udm/dmm_units')
        print(f"[*] Post-run DMM Units: {len(units.decode('latin1').splitlines())} lines (expected clean)")

if __name__ == '__main__':
    main()
