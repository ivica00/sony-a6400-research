"""CPU-only stop/register/resume receipt, gated by fresh owner observations."""
import argparse, hashlib, json, re, shlex
from datetime import datetime, timezone
from contextlib import nullcontext
from pathlib import Path
from tools.camera_debugger import connect
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT
from tools.research.validate_uvc_ptp_owner_receipts import load


def main(argv=None,debugger=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--owners',required=True,type=Path)
    p.add_argument('--output-dir',required=True,type=Path)
    p.add_argument('--probe-build',type=Path,default=ROOT/'artifacts/native/uvc-ptp-freeze-e0192')
    p.add_argument('--attest-device',help='Existing RAM character node for idle module diagnostics only')
    p.add_argument('--route-shadow',action='store_true',help='Exercise module-owned test word; never native route')
    p.add_argument('--entry-hook',action='store_true',help='Exercise native entry hook cycle (publish -> sync -> retire -> sync)')
    args=p.parse_args(argv);expected=load(args.owners)
    if args.route_shadow and not args.attest_device:p.error('--route-shadow requires --attest-device')
    if args.entry_hook and not args.attest_device:p.error('--entry-hook requires --attest-device')
    if args.entry_hook and args.route_shadow:p.error('--entry-hook and --route-shadow are mutually exclusive')
    out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    out.mkdir(parents=True,exist_ok=False)
    build=args.probe_build.resolve()
    if not build.is_relative_to(ROOT/'artifacts'):p.error('Probe build must be under artifacts')
    binary=build/'native_usb_freeze_probe.elf'
    data=binary.read_bytes()
    manifest=json.loads((build/'manifest.json').read_text())
    records=[r for path,r in manifest['files'].items() if Path(path).name==binary.name]
    if len(records)!=1 or records[0]['bytes']!=len(data) or records[0]['sha256']!=hashlib.sha256(data).hexdigest():
        raise ValueError('Probe build identity mismatch')
    remote='/tmp_bt/uvc_cpu_barrier_'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    log=remote+'.log'
    report=dict(status='started',camera_payload=remote,camera_log=log,files={},
                mode_switch=False,module_load=False,hooks=False,scope='PID149 CPU barrier only; /tmp_bt payload/log')
    if args.attest_device and not re.fullmatch(r'/tmp_bt/[A-Za-z0-9_-]+',args.attest_device):
        p.error('Diagnostic device must be a simple RAM /tmp_bt path')
    def save():(out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    def artifact(name,raw):
        (out/name).write_bytes(raw)
        report['files'][name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    def read(dbg,path,name,limit):
        raw,short=dbg.read_all(path,limit);artifact(name,raw)
        if short:raise RuntimeError('Truncated '+path)
        return raw
    save()
    try:
        with (connect() if debugger is None else nullcontext(debugger)) as dbg:
            artifact('debugger-before.txt',dbg.request(1)['payload'])
            status=read(dbg,'/proc/149/status','status-before.txt',16384).decode('ascii')
            if not re.search(r'^TracerPid:\s+0$',status,re.M):raise RuntimeError('Owner already traced')
            if not re.search(r'^Threads:\s+'+str(len(expected['tasks']))+r'$',status,re.M):raise RuntimeError('Owner thread count changed')
            result=dbg.request(3,('test ! -e '+shlex.quote(remote)).encode())
            if result['status'] or result['flags']:raise RuntimeError('Payload path check failed')
            report['upload']=dbg.push(remote,data)
            result=dbg.request(3,('chmod 700 '+shlex.quote(remote)).encode())
            if result['status'] or result['flags']:raise RuntimeError('chmod failed')
            extra=' --attest-device '+shlex.quote(args.attest_device) if args.attest_device else ''
            if args.route_shadow:extra+=' --route-shadow'
            if args.entry_hook:extra+=' --entry-hook'
            result=dbg.request(3,(shlex.quote(remote)+' --capture-once'+extra+' > '+shlex.quote(log)).encode())
            report['run']=dict(status=result['status'],flags=result['flags']);save()
            raw=read(dbg,log,'freeze.log',256*1024);text=raw.decode('ascii')
            after=read(dbg,'/proc/149/status','status-after.txt',16384).decode('ascii')
            artifact('debugger-after.txt',dbg.request(1)['payload'])
            if args.attest_device:
                attestation=re.search(r'^ATTEST result=(-?\d+) errno=(\d+) completed=(\d+) expected=(\d+) error=(-?\d+)$',text,re.M)
                if attestation:
                    values=list(map(int,attestation.groups()))
                    report['native_stop_diagnostic']=dict(zip(('result','errno','completed','expected','error'),values))
                    save()
                if not attestation or values[0] or values[1] or values[4] or values[2]!=values[3]:
                    raise RuntimeError('Module stop diagnostic failed or incomplete')
            if args.route_shadow:
                if not re.search(r'^ROUTE_SHADOW native_route_writes=0$',text,re.M):raise RuntimeError('Missing shadow-route receipt')
                report['route_shadow_only']=True
            if args.entry_hook:
                if not re.search(r'^ENTRY_HOOK verified_publication_cycle=1$',text,re.M):raise RuntimeError('Missing entry-hook receipt')
                report['entry_hook_cycle']=True
            if result['status'] or result['flags']:raise RuntimeError('CPU helper failed')
            receipt=re.search(r'^FREEZE threads=(\d+) attached=(\d+) resumed=(\d+) result=(-?\d+) elapsed_ms=(\d+)$',text,re.M)
            end=re.search(r'^END result=0 captured=(\d+) expected=(\d+) saved_user_regs_only=1$',text,re.M)
            if not receipt or not end:raise RuntimeError('Incomplete CPU receipt')
            count,attached,resumed,result,elapsed=map(int,receipt.groups())
            tids=[int(t) for t in re.findall(r'^REG tid=(\d+) ',text,re.M)]
            stops=re.findall(r'^STOP tid=(\d+) wchan=(\S+)(?: signal=\d+ info_signal=-?\d+ info_code=-?\d+)?$',text,re.M)
            if stops:
                if sorted(int(t) for t,w in stops)!=sorted(tids):raise RuntimeError('Incomplete stop-site receipt')
                report['stop_sites']={w:sum(1 for t,v in stops if v==w) for t,w in stops}
            reasons=re.findall(r'^STOP tid=(\d+) wchan=\S+ signal=(\d+) info_signal=(-?\d+) info_code=(-?\d+)$',text,re.M)
            if reasons:
                if sorted(int(t) for t,s,i,c in reasons)!=sorted(tids):raise RuntimeError('Incomplete stop-reason receipt')
                report['stop_reasons']={}
                for t,s,i,c in reasons:
                    key=f'wait={s},info={i},code={c}'
                    report['stop_reasons'][key]=report['stop_reasons'].get(key,0)+1
            if (result or count!=attached or count!=resumed or len(tids)!=count or len(set(tids))!=count
                or list(map(int,end.groups()))!=[count,count]):raise RuntimeError('CPU receipt counts differ')
            if sorted(tids)!=sorted(tid for pid,tid in expected['tasks']):raise RuntimeError('Fresh observed TID set changed')
            if not re.search(r'^TracerPid:\s+0$',after,re.M):raise RuntimeError('Tracer remains attached')
            report.update(status='cpu_barrier_receipt_passed',threads=count,elapsed_ms=elapsed,tracer_detached=True,
                limitations=['User registers and optional proc wchan observation; no kernel stack unwind or VFS/IRQ/DMA drain proof.',
                             'Observed owners are not locked against future opens; no route publication.'])
            save()
    except Exception as error:
        report.update(status='failed',error=repr(error));save();raise
    print(json.dumps({k:v for k,v in report.items() if k!='files'},indent=2))


if __name__=='__main__':main()
