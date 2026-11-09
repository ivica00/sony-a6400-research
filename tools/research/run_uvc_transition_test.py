import subprocess
import time
import json
import threading

def get_pnp_devices():
    ps_cmd = "Get-PnpDevice | Where-Object { $_.InstanceId -match '054C' -or $_.Class -eq 'Camera' -or $_.InstanceId -match '0322' } | Select-Object Status, ConfigManagerErrorCode, Class, FriendlyName, InstanceId | ConvertTo-Json"
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
    if not res.stdout.strip():
        return []
    try:
        data = json.loads(res.stdout)
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception:
        return []

def monitor_pnp(stop_event, log_list):
    seen = set()
    start_time = time.time()
    while not stop_event.is_set():
        devs = get_pnp_devices()
        t = time.time() - start_time
        for d in devs:
            inst = d.get('InstanceId', '')
            status = d.get('Status', '')
            err = d.get('ConfigManagerErrorCode', '')
            cls = d.get('Class', '')
            name = d.get('FriendlyName', '')
            key = (status, err, cls, name, inst)
            if key not in seen:
                seen.add(key)
                entry = f"[{t:6.2f}s] [{status} err={err}] {cls} - {name} ({inst})"
                print(entry)
                log_list.append(entry)
        time.sleep(0.5)

def main():
    print("=== Step 1: Current baseline devices ===")
    baseline = get_pnp_devices()
    for d in baseline:
        print(f"[{d.get('Status')}] {d.get('Class')} - {d.get('FriendlyName')} ({d.get('InstanceId')})")

    stop_event = threading.Event()
    pnp_log = []
    t = threading.Thread(target=monitor_pnp, args=(stop_event, pnp_log), daemon=True)
    t.start()

    print("\n=== Step 2: Triggering /tmp_bt/run_feeder.sh in background on camera ===")
    try:
        res = subprocess.run(
            ["py", "-3.12", "tools/camera_debugger.py", "exec", "/tmp_bt/run_feeder.sh &"],
            capture_output=True, text=True, timeout=10
        )
        print("Camera exec stdout:\n", res.stdout)
        if res.stderr:
            print("Camera exec stderr:\n", res.stderr)
    except Exception as e:
        print("Exec error:", e)

    print("\n=== Step 3: Waiting 22s for UVC session (720p @ 30 FPS) & automatic return ===")
    time.sleep(22)
    stop_event.set()
    t.join(timeout=2)

    print("\n=== Step 4: Reading camera feeder.log & dmesg ===")
    try:
        res = subprocess.run(
            ["py", "-3.12", "tools/camera_debugger.py", "exec", "cat /log/feeder.log"],
            capture_output=True, text=True, timeout=10
        )
        print("--- /log/feeder.log ---")
        print(res.stdout)
    except Exception as e:
        print("Failed to read feeder.log:", e)

    try:
        res = subprocess.run(
            ["py", "-3.12", "tools/camera_debugger.py", "exec", "dmesg"],
            capture_output=True, text=True, timeout=10
        )
        print("--- dmesg ---")
        lines = res.stdout.splitlines()
        for line in lines[-40:]:
            print(line)
    except Exception as e:
        print("Failed to read dmesg:", e)

if __name__ == "__main__":
    main()
