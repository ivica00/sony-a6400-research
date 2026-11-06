import subprocess

cmd = 'Get-PnpDevice -PresentOnly | Where-Object { $_.Class -eq "USB" -or $_.Class -eq "USBDevice" -or $_.Class -eq "DiskDrive" } | Select-Object Status, Class, FriendlyName, InstanceId | ConvertTo-Json'
p = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
print("ALL USB/DISKS:\n", p.stdout)
