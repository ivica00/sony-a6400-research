import subprocess

cmd = '''Get-PnpDevice | Where-Object { $_.InstanceId -like "*054C*" } | Format-Table Status, Class, FriendlyName, InstanceId -AutoSize'''
p = subprocess.run(['powershell', '-NoProfile', '-Command', cmd], capture_output=True, text=True)
print(p.stdout)
