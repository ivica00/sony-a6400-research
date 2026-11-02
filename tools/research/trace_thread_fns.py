with open("src/a6400/execution/guest_uipc.py", "r", encoding="utf-8") as f:
    text = f.read()

lines = text.splitlines()
for i, line in enumerate(lines[:100]):
    print(f"{i+1}: {line}")
