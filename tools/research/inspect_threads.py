import json

with open("artifacts/execution/ui-boot-subdevice1-100m.json", "r") as f:
    rep = json.load(f)

threads = rep.get("threads", {})
print("Threads summary:")
for tid, t in threads.items():
    print(f"  TID {tid}: name={t.get('name')}, state={t.get('state')}, tls={t.get('tls_val')}, child_stack={t.get('child_stack')}")

events = rep.get("thread_events", [])
print(f"\nThread events ({len(events)}):")
for ev in events:
    print(" ", ev)
