import json

with open("artifacts/execution/ui-boot-subdevice1-100m.json", "r") as f:
    rep = json.load(f)

for s in rep.get("serviced_syscalls", []):
    if s.get("syscall") == "clone":
        tid = s.get("child_tid")
        pc = s.get("child_resume_pc")
        sp = s.get("child_stack")
        tls = s.get("tls_val")
        print(f"Clone child {tid}: resume_pc=0x{pc:x}, stack=0x{sp:x}, tls=0x{tls:x}")
