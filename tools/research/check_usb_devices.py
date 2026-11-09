import subprocess
import json

def get_devices():
    ps_cmd = "Get-PnpDevice | Where-Object { $_.InstanceId -match '054C' -or $_.Class -eq 'Camera' } | Select-Object Status, Class, FriendlyName, InstanceId | ConvertTo-Json"
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
    if not res.stdout.strip():
        return []
    try:
        data = json.loads(res.stdout)
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception as e:
        print("JSON parse error:", e, "output:", res.stdout)
        return []

if __name__ == "__main__":
    devs = get_devices()
    for d in devs:
        print(f"[{d.get('Status')}] {d.get('Class')} - {d.get('FriendlyName')} ({d.get('InstanceId')})")
