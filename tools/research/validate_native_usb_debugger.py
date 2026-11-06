"""Validate the installed debugger in native USB mode and retain actual results."""
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime
from tools.camera_debugger import connect,DebuggerError,MAX_DATA

ROOT=Path(__file__).resolve().parents[2]


def main():
    destination=ROOT/'artifacts/hardware'/('native-usb-debug-validation-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    destination.mkdir(parents=True,exist_ok=False)
    report={'mode_switches':False,'checks':{}}
    def save(name,data):
        (destination/name).write_bytes(data)
        return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    with connect() as debugger:
        info=debugger.request(1)['payload']; report['checks']['info']=save('info.txt',info)
        print(info.decode())
        for name,command in [('identity',"while IFS= read -r line; do case \"$line\" in Uid:*|Gid:*|CapEff:*) printf '%s\\n' \"$line\";; esac; done < /proc/self/status"),
                             ('exit_status','printf ok; exit 7'),
                             ('output_limit','i=0; while [ "$i" -lt 5000 ]; do printf x; i=$((i+1)); done'),('timeout','sleep 6')]:
            started=time.monotonic()
            try:
                result=debugger.request(3,command.encode())
                row=save(name+'.bin',result['payload'])
                row.update(status=result['status'],flags=result['flags'])
                if name=='identity': row['passed']=result['status']==0 and b'Uid:\t0\t0\t0\t0' in result['payload']
                elif name=='exit_status': row['passed']=result['status']==7 and result['payload']==b'ok'
                elif name=='output_limit': row['passed']=result['status']==0 and len(result['payload'])==MAX_DATA and bool(result['flags']&1)
                else: row['passed']=False
            except DebuggerError as exc:
                row={'status':exc.status,'passed':name=='timeout' and exc.status==-110}
            except Exception as exc:
                row={'error':repr(exc),'passed':False}
            row['elapsed_seconds']=round(time.monotonic()-started,3)
            report['checks'][name]=row
            (destination/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(name,row)
        for name,op,arg in [('processes',6,0),('threads',7,149)]:
            result=debugger.request(op,arg0=arg)
            report['checks'][name]=save(name+'.txt',result['payload'])
            report['checks'][name]['flags']=result['flags']
        for name,path in [('im_comm','/proc/149/comm'),('im_status','/proc/149/status'),
                          ('im_maps','/proc/149/maps'),('debug_status','/proc/self/status')]:
            data,truncated=debugger.read_all(path)
            report['checks'][name]=save(name+'.txt',data)
            report['checks'][name]['truncated']=truncated
        for name,address,size in [('input_gate',0x060e7188,28),('menu_gate',0x15b53cb0,26)]:
            try:
                data=debugger.memory(149,address,size)
                report['checks'][name]=save(name+'.bin',data)
                report['checks'][name]['hex']=data.hex()
                print(name,data.hex())
            except Exception as exc:
                report['checks'][name]={'error':repr(exc)}
    (destination/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(destination)


if __name__=='__main__': main()
