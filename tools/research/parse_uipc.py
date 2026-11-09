with open('artifacts/live_uipc_dump.txt', 'r', encoding='utf-8') as f:
    text = f.read()

lines = text.splitlines()

for section in ['GMSGQ', 'LMSGQ']:
    print(f"=== {section} with W > 0 or M > 0 ===")
    in_sec = False
    for l in lines:
        if l.startswith('[] ' + section):
            in_sec = True
            continue
        elif in_sec and l.startswith('[]'):
            break
        elif in_sec and l.strip():
            parts = l.split()
            if len(parts) >= 9 and parts[0] != 'ID(Hex)':
                qid = parts[0]
                m = int(parts[1])
                w = int(parts[8]) if len(parts) > 8 else 0
                if m > 0 or w > 0:
                    print(f"  QID 0x{qid}: M={m}, W={w} | full: {l}")
