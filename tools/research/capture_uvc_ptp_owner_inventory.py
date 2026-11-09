"""Run only the read-only inventory helper; camera payload/log writes in /tmp_bt."""
import argparse,hashlib,json,re,shlex
from datetime import datetime,timezone
from pathlib import Path
from tools.camera_debugger import connect
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT

EXPECTED='6302bf9333e0cb2032771b0f4b1abfe4fac40bea85a44d0684990ae17ba4ef83'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',required=True,type=Path)
    args=p.parse_args();out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    out.mkdir(parents=True,exist_ok=False)
    binary=ROOT/'artifacts/native/uvc-ptp-owner-inventory-e0177/uvc_ptp_owner_inventory'
    data=binary.read_bytes();assert hashlib.sha256(data).hexdigest()==EXPECTED
    suffix=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    remote='/tmp_bt/uvc_owner_inventory_'+suffix;log=remote+'.log'
    report=dict(status='started',captured_utc=datetime.now(timezone.utc).isoformat(),
        camera_payload=remote,camera_log=log,camera_writes_scope='/tmp_bt only',
        mode_switch=False,module_load=False,freeze=False,files={},owners=[],tasks=[])
    def save(): (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    def artifact(name,raw):
        (out/name).write_bytes(raw)
        report['files'][name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    save()
    try:
        with connect() as dbg:
            artifact('debugger-before.txt',dbg.request(1)['payload'])
            result=dbg.request(3,('test ! -e '+shlex.quote(remote)).encode())
            if result['status'] or result['flags']:raise RuntimeError('Payload path exists or check failed')
            report['upload']=dbg.push(remote,data);save()
            result=dbg.request(3,('chmod 700 '+shlex.quote(remote)).encode())
            if result['status'] or result['flags']:raise RuntimeError('RAM chmod failed')
            result=dbg.request(3,(shlex.quote(remote)+' > '+shlex.quote(log)).encode())
            report['run']=dict(status=result['status'],flags=result['flags'])
            raw,truncated=dbg.read_all(log,256*1024);artifact('owners.log',raw)
            report['log_truncated']=truncated
            text=raw.decode('ascii',errors='strict')
            report['owners']=[dict(pid=int(a),fd=int(b)) for a,b in re.findall(r'^OWNER pid=(\d+) fd=(\d+) major=242 minor=1$',text,re.M)]
            report['tasks']=[dict(pid=int(a),tid=int(b)) for a,b in re.findall(r'^TASK pid=(\d+) tid=(\d+)$',text,re.M)]
            end=re.search(r'^END owners=(\d+) threads=(\d+) errors=(\d+) observational=1$',text,re.M)
            if end:
                report['summary']=dict(zip(('owners','threads','errors'),map(int,end.groups())))
                if report['summary']['owners']!=len(report['owners']) or report['summary']['threads']!=len(report['tasks']):raise RuntimeError('Record counts differ')
            for pid in sorted({r['pid'] for r in report['owners']}):
                for name,limit in [('comm',4096),('status',16384),('maps',512*1024)]:
                    content,short=dbg.read_all(f'/proc/{pid}/{name}',limit)
                    filename=f'pid-{pid}-{name}.txt';artifact(filename,content)
                    report['files'][filename]['truncated']=short
            artifact('debugger-after.txt',dbg.request(1)['payload'])
            report['status']='observational_inventory_complete' if end and not truncated and not result['status'] and not report['summary']['errors'] else 'observational_inventory_incomplete'
            report['limitations']=['No threads stopped; proc/FD state can change during enumeration.',
                'This is not proof that old kernel ioctl calls or USB callbacks have drained.',
                'Payload/log remain in RAM /tmp_bt; no persistent camera paths modified.']
            save()
    except Exception as error:
        report['status']='failed';report['error']=repr(error);save();raise
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
