"""Read the actual USB live-view status byte via a verified original getter.

Uses bounded read-only ptrace through the existing debugger. Does not call the
getter or setter, write RAM, start a stream or change USB mode.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from tools.camera_debugger import connect
from tools.research.remote_elf import RemoteElf32, debugger_reader

ROOT=Path(__file__).resolve().parents[2]
NAME='_ZN17MrpwDeviceManager17GetLiveViewStatusEv'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args();out=args.report_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):
        parser.error('Report must remain under artifacts')
    out.mkdir(parents=True,exist_ok=False)
    report={'pid':149,'camera_writes':False,'mode_switches':False,
            'ptrace':'bounded individual read calls, not an atomic snapshot'}
    try:
        with connect() as dbg:
            maps,truncated=dbg.read_all('/proc/149/maps',256*1024)
            if truncated: raise ValueError('Truncated process maps')
            (out/'maps.txt').write_bytes(maps)
            parsed=[]
            for line in maps.decode().splitlines():
                parts=line.split();a,b=(int(v,16) for v in parts[0].split('-'))
                parsed.append((a,b,parts[1],int(parts[2],16),parts[-1]))
            ranges=[r for r in parsed if r[4]=='/usr/lib/libInfraRemote.so' and r[3]==0 and 'x' in r[2]]
            if len(ranges)!=1:raise ValueError('Ambiguous loaded library mapping')
            elf=RemoteElf32(debugger_reader(dbg,'/usr/lib/libInfraRemote.so'))
            zero=[s for s in elf.segments if s[0]==1 and s[1]==0]
            if len(zero)!=1:raise ValueError('Ambiguous ELF first segment')
            bias=ranges[0][0]-zero[0][2]
            sym=elf.resolve(NAME);linked=sym['value']&~1
            if sym['size']!=24:raise ValueError('Unexpected getter size')
            original=elf.virtual(linked,24);runtime=bias+linked
            code=dbg.memory(149,runtime,24);(out/'getter.bin').write_bytes(code)
            if code!=original:raise ValueError('Live getter differs from actual camera file')
            # Exact validated original instructions through pop, excluding literals.
            if code[:16]!=bytes.fromhex('034b044a7b4480b500af9b58187880bd'):
                raise ValueError('Unrecognized getter instruction contract')
            delta,index=struct.unpack_from('<2I',code,16)
            slot=(runtime+8+delta+index)&0xffffffff
            if not any(a<=slot and slot+4<=b and 'r' in perm for a,b,perm,_,_ in parsed):
                raise ValueError('GOT slot outside readable mapping')
            slotdata=dbg.memory(149,slot,4);(out/'slot.bin').write_bytes(slotdata)
            address=struct.unpack('<I',slotdata)[0]
            if not any(a<=address<b and 'w' in perm and path=='/usr/lib/libInfraRemote.so'
                       for a,b,perm,_,path in parsed):
                raise ValueError('Status target outside owner writable library mapping')
            value=dbg.memory(149,address,1);(out/'status.bin').write_bytes(value)
            report.update(symbol=sym,load_bias=hex(bias),getter_runtime=hex(runtime),
                getter_sha256=hashlib.sha256(code).hexdigest(),source_equal=True,
                got_slot=hex(slot),status_address=hex(address),raw_status=value[0],
                limitations=['Opaque status byte; not stream capability, active JPEG source or frame delivery proof.'])
    except Exception as exc:
        report['error']=repr(exc)
        raise
    finally:
        (out/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
