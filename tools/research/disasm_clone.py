import json

with open("artifacts/execution/ui-boot-subdevice1-100m.json", "r") as f:
    rep = json.load(f)

for s in rep.get("serviced_syscalls", [])[1085:1105]:
    print(s)
