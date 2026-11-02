import json

with open("artifacts/execution/ui-boot-subdevice1-100m.json", "r") as f:
    rep = json.load(f)

opens = [s for s in rep.get("serviced_syscalls", []) if s.get("syscall") == "open"]
print(f"Total open syscalls: {len(opens)}")
for o in opens:
    path = o.get("path") or o.get("pathname") or o.get("arg0")
    flags = o.get("flags")
    ret = o.get("returned")
    print(f"open: {path} (flags {flags}) -> fd {ret}")
