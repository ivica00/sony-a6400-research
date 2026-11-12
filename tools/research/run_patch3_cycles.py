import sys, json, time, hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'Sony-PMCA-RE'))
from tools import camera_debugger as cd
NAME = 'a6400_dbg_patch3'
MOD = ROOT / 'artifacts/native/a6400-dbg-patch3-e0407a/final/a6400_dbg_patch3.ko'
STAGE = '/tmp_bt/a6400_dbg_patch3.ko'
out = {'module_sha256': hashlib.sha256(MOD.read_bytes()).hexdigest(), 'cycles': []}
with cd.connect() as d:
    out['pushed'] = d.push(STAGE, MOD.read_bytes())
    for cycle in (1, 2):
        entry = {'cycle': cycle}
        r = d.request(cd.OP_EXEC, f'/sbin/insmod {STAGE}; echo exit=$?'.encode())
        entry['insmod'] = (r['status'], r['payload'].decode('latin1', 'replace').strip())
        time.sleep(0.5)
        log = d.dmesg(limit=0x20000)[0].decode('latin1', 'replace')
        entry['load_log'] = [l for l in log.splitlines() if 'A6400DBG3' in l]
        mods = d.read('/proc/modules', 0, cd.MAX_DATA).decode('latin1')
        entry['loaded'] = any(l.split() and l.split()[0] == NAME for l in mods.splitlines() if l.split())
        unload = d.request(cd.OP_EXEC, f'/sbin/rmmod {NAME}; echo exit=$?'.encode())
        entry['rmmod'] = (unload['status'], unload['payload'].decode('latin1', 'replace').strip())
        time.sleep(0.5)
        log = d.dmesg(limit=0x20000)[0].decode('latin1', 'replace')
        entry['unload_log'] = [l for l in log.splitlines() if 'A6400DBG3' in l]
        mods = d.read('/proc/modules', 0, cd.MAX_DATA).decode('latin1')
        entry['still_loaded'] = any(l.split() and l.split()[0] == NAME for l in mods.splitlines() if l.split())
        out['cycles'].append(entry)
    d.request(cd.OP_EXEC, b'rm -f ' + STAGE.encode() + b'; echo cleaned')
    out['ping'] = d.ping().strip()
    out['uptime'] = d.request(cd.OP_EXEC, b'cat /proc/uptime')['payload'].decode().strip()
    text, total, _ = d.dmesg(limit=0x20000)
    open(ROOT / 'artifacts/hardware/e0407a-dmesg.txt', 'wb').write(text)
out['result'] = 'ok' if all(not c['still_loaded'] and c['loaded'] for c in out['cycles']) else 'failed'
(ROOT / 'artifacts/hardware/e0407a-three-target.json').write_text(json.dumps(out, indent=2), encoding='utf-8')
print(json.dumps({'result': out['result'], 'log': out['cycles'][-1]['unload_log'][-3:]}, indent=2))
