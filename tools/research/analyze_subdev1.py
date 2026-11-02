import json

def analyze():
    path = "artifacts/execution/ui-boot-subdevice1-100m.json"
    with open(path, "r", encoding="utf-8") as f:
        rep = json.load(f)

    print("=== Execution Overview ===")
    print("Status:", rep.get("status"))
    print("Instructions executed:", rep.get("instructions_executed"))
    print("Syscall responses supplied:", rep.get("syscall_responses_supplied"))
    print("Final PC:", hex(rep.get("pc", 0)) if isinstance(rep.get("pc"), int) else rep.get("pc"))

    threads = rep.get("threads", {})
    print(f"\n=== Threads ({len(threads)}) ===")
    for tid, th in sorted(threads.items()):
        pc = hex(th.get("pc", 0)) if isinstance(th.get("pc"), int) else th.get("pc")
        sp = hex(th.get("sp", 0)) if isinstance(th.get("sp"), int) else th.get("sp")
        print(f"  TID {tid}: state={th.get('state')} pc={pc} sp={sp}")

    serviced = rep.get("serviced_syscalls", [])
    print(f"\n=== Syscalls (total {len(serviced)}) ===")
    
    # Count syscalls by type
    counts = {}
    for s in serviced:
        name = s.get("syscall", f"r7_{s.get('r7')}")
        counts[name] = counts.get(name, 0) + 1
    print("Syscall breakdown:", counts)

    # Let's inspect unique ioctls on fd 10
    fd10_calls = [s for s in serviced if s.get("fd") == 10]
    print(f"\nTotal fd=10 (/dev/dmpgles2) calls: {len(fd10_calls)}")
    cmd_counts = {}
    for s in fd10_calls:
        cmd = s.get("cmd")
        cmd_hex = hex(cmd) if isinstance(cmd, int) else str(cmd)
        cmd_counts[cmd_hex] = cmd_counts.get(cmd_hex, 0) + 1
    print("fd=10 cmd breakdown:", cmd_counts)

    # Show last 40 syscalls
    print("\n=== Last 40 Syscalls ===")
    for s in serviced[-40:]:
        print("  ", s)

if __name__ == "__main__":
    analyze()
