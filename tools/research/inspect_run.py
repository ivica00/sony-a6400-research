import json
from pathlib import Path

def main():
    path = Path('artifacts/execution/interpreter-threads.json')
    if not path.exists():
        print("Report not found")
        return
    data = json.loads(path.read_text(encoding='utf-8'))
    
    # Map fds to paths
    fd_to_path = {}
    for s in data.get('serviced_syscalls', []):
        if s.get('syscall') == 'open':
            print(f"open: fd={s.get('returned')} path={s.get('path')}")
        elif s.get('syscall') == 'close':
            print(f"close: fd={s.get('arguments', [None])[0]}")
            
    mmaps = [s for s in data.get('serviced_syscalls', []) if s.get('syscall') == 'mmap2']
    print(f"Total mmap2 calls: {len(mmaps)}")
    if mmaps:
        print("mmap keys:", mmaps[0].keys())
        print("first mmap:", mmaps[0])
    for m in mmaps:
        args = m.get('arguments', [])
        ret = m.get('returned', 0)
        length = args[1] if len(args) > 1 else 0
        fd = args[4] if len(args) > 4 else -1
        p = fd_to_path.get(fd, f'anon/fd{fd}')
        if ret <= 0x5025fa60 < ret + length:
            print(f"*** HIT: 0x5025fa60 is inside [{hex(ret)} - {hex(ret+length)}]: {p} (offset {hex(0x5025fa60 - ret)})")
        if 0x50000000 <= ret <= 0x50400000:
            print(f"[{hex(ret)} - {hex(ret+length)}] fd={fd} ({p})")

if __name__ == '__main__':
    main()
