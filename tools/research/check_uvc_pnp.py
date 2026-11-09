import subprocess
import json

cmd = "Get-PnpDevice | Where-Object { $_.InstanceId -like '*0322*' } | Select-Object FriendlyName, InstanceId, Status, Problem, ConfigManagerErrorCode | ConvertTo-Json"
p = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
print(p.stdout)
