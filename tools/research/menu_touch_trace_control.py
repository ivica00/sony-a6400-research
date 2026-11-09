"""Check/install/read/remove the finite, forwarding-only exact-version UI logger."""
import argparse,hashlib,json,struct
from datetime import datetime
from pathlib import Path
from tools.camera_debugger import connect
from tools.research.remote_elf import RemoteElf32,debugger_reader
from tools.research.active_menu_snapshot_probe import ROOT,HW
ACTIVE=HW/'menu-touch-trace-active.json'
def request(meta,code,operation):
    checksum=2166136261
    for byte in code:checksum=((checksum^byte)*16777619)&0xffffffff
    return struct.pack('<8I',0x4d544852,1,operation,len(code),int(meta['entry'],16),checksum,1184,0x6309d48)+code

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['check','install','read','remove'])
    args=parser.parse_args()
    if args.action=='remove' or (args.action=='read' and ACTIVE.exists()):
        active=json.loads(ACTIVE.read_text());meta=active['build'];path=Path(active['payload'])
        if not path.resolve().is_relative_to(HW.resolve()):raise ValueError('Recovery payload outside evidence directory')
        code=path.read_bytes()
    else:
        meta=json.loads((HW/'menu-touch-trace-build.json').read_text());code=(HW/'menu-touch-trace-payload.bin').read_bytes()
    if hashlib.sha256(code).hexdigest()!=meta['sha256']:raise ValueError('Payload hash differs')
    stem=HW/('menu-touch-trace-'+args.action+'-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    receipt=dict(action=args.action,build=meta,selection_enabled=False,remote_application_calls=False)
    with connect() as d:
        maps,truncated=d.read_all('/proc/149/maps')
        if truncated:raise ValueError('Incomplete mappings')
        bases=[int(line.split('-')[0],16) for line in maps.decode().splitlines() if line.endswith('/libObj.so') and 'r-xp 00000000 ' in line]
        if bases!=[0x5d18000]:raise ValueError('Wrong original libObj base')
        elf=RemoteElf32(debugger_reader(d,'/usr/lib/libObj.so'))
        if elf.virtual(0x6309d48-0x5d18000,12).hex()!=meta['expected_prologue']:raise ValueError('Original release consumer differs')
        segments=[s for s in elf.segments if s[0]==1]
        ends={s[6]:0x5d18000+s[2]+s[5] for s in segments}
        if ends.get(5)!=0x700d708 or ends.get(6)!=0x7143920:raise ValueError('ELF padding ownership differs')
        if args.action in ('read','remove'):
            raw=d.memory(149,0x7143920,1184);stem.with_suffix('.state.bin').write_bytes(raw)
            header=struct.unpack_from('<8I',raw);events=[]
            expected_hook=bytes.fromhex('dff800f0')+struct.pack('<I',int(meta['entry'],16))+bytes.fromhex('00bf00bf')
            live_hook=d.memory(149,0x6309d48,12)
            receipt.update(hook_bytes=live_hook.hex(),hook_installed=live_hook==expected_hook)
            if header[0]==0x4d544c47 and header[1]==1 and header[5]==24:
                for i in range(min(header[3],24)):
                    row=struct.unpack_from('<12I',raw,32+i*48)
                    if row[0]!=i+1:continue
                    xy=lambda value:list(struct.unpack('<hh',struct.pack('<I',value)))
                    events.append(dict(sequence=row[0],tid=row[1],system=hex(row[2]),before_framebuffer_xy=xy(row[3]),mouse=row[4]&255,button=(row[4]>>8)&255,framebuffer_xy=xy(row[5]),raw_xy=xy(row[6]),buttons=row[7],clock_raw=[row[8],row[9]],native_result=hex(row[10]),transport_type=row[11]))
            receipt.update(header=list(header),committed_events=events,live_read_non_atomic=True)
            if args.action=='read':print(json.dumps(receipt,indent=2))
        if args.action!='read':
            helper=(ROOT/'devcrashday_a6400/native_menu_touch_trace_guard.elf').read_bytes()
            d.push('/setting/native_menu_touch_trace_guard.elf',helper)
            readback,truncated=d.read_all('/setting/native_menu_touch_trace_guard.elf')
            if truncated or readback!=helper:raise ValueError('Helper readback differs')
            packet=request(meta,code,{'check':0,'install':1,'remove':2}[args.action])
            d.push('/setting/menu_touch_trace.req',packet)
            readback,truncated=d.read_all('/setting/menu_touch_trace.req')
            if truncated or readback!=packet:raise ValueError('Request readback differs')
            receipt.update(helper_sha256=hashlib.sha256(helper).hexdigest(),request_sha256=hashlib.sha256(packet).hexdigest())
            if args.action=='install':
                payload=stem.with_suffix('.payload.bin');payload.write_bytes(code)
                ACTIVE.write_text(json.dumps(dict(build=meta,payload=str(payload),installed=False,attempted=True),indent=2))
            result=d.request(3,b'chmod 755 /setting/native_menu_touch_trace_guard.elf; /setting/native_menu_touch_trace_guard.elf')
            receipt.update(status=result['status'],flags=result['flags'],log=result['payload'].decode());print(receipt['log'])
            ok=not result['status'] and not result['flags'] and 'END result=0 ' in receipt['log']
            if args.action=='install':
                active=json.loads(ACTIVE.read_text());active.update(installed=ok,receipt=str(stem.with_suffix('.json')));ACTIVE.write_text(json.dumps(active,indent=2))
            if args.action=='remove' and ok:
                active=json.loads(ACTIVE.read_text());active.update(installed=False,removed=True,removal_receipt=str(stem.with_suffix('.json')));ACTIVE.write_text(json.dumps(active,indent=2))
            stem.with_suffix('.json').write_text(json.dumps(receipt,indent=2))
            if not ok:raise ValueError('Guard did not complete; inspect retained receipt')
    stem.with_suffix('.json').write_text(json.dumps(receipt,indent=2))
    print(stem.with_suffix('.json'))
if __name__=='__main__':main()
