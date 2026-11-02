with open("src/a6400/execution/interpreter_probe.py", "r", encoding="utf-8") as f:
    text = f.read()

for line in text.splitlines()[:50]:
    if "import" in line or "from" in line:
        print(line)
