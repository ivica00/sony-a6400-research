import sys, os, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from tools.camera_debugger import connect

def main():
    arm_bin = 'tools/native_camera/uvc_acquire_single_jpeg_arm'
    with open(arm_bin, 'rb') as f:
        data = f.read()
    
    with connect() as d:
        d.push('/tmp_bt/uvc_acquire_single_jpeg_arm', data)
        d.request(3, b'chmod 755 /tmp_bt/uvc_acquire_single_jpeg_arm')
        d.request(3, b'rm -f /tmp_bt/acq.log')
        print("Launching uvc_acquire_single_jpeg_arm...")
        d.request(3, b'sh -c "/tmp_bt/uvc_acquire_single_jpeg_arm > /tmp_bt/acq.log 2>&1 &"')
        for i in range(12):
            time.sleep(1)
            log, _ = d.read_all('/tmp_bt/acq.log')
            txt = log.decode(errors='replace')
            print(f"--- T+{i+1}s ---")
            for l in txt.strip().splitlines()[-8:]:
                print(" ", l)
            if 'ACQUISITION EXECUTION FINISHED' in txt:
                break

if __name__ == '__main__':
    main()
