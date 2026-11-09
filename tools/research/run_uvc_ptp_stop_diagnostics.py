"""Scoped idle-module stop diagnostic; no route publication or activation."""
import argparse, hashlib, io, json, re, shlex
from contextlib import ExitStack, nullcontext, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from tools.camera_debugger import connect
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT
from tools.research.validate_uvc_ptp_owner_receipts import load
from tools.research.capture_uvc_ptp_cpu_barrier import main as capture_cpu


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--owners',required=True,type=Path)
    p.add_argument('--output-dir',required=True,type=Path)
    p.add_argument('--module-build',type=Path,default=ROOT/'artifacts/native/uvc-ptp-module-e0196')
    p.add_argument('--module-audit',type=Path,default=ROOT/'artifacts/analysis/uvc-ptp-module-e0196')
    p.add_argument('--probe-build',type=Path,default=ROOT/'artifacts/native/uvc-ptp-freeze-e0197')
    p.add_argument('--route-shadow',action='store_true',help='Only module-owned slot lifecycle test')
    p.add_argument('--entry-hook',action='store_true',help='Native entry hook publication and retirement under stop scope')
    args=p.parse_args();load(args.owners)
    if args.entry_hook and args.route_shadow:p.error('--entry-hook and --route-shadow are mutually exclusive')
    out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    build=args.module_build.resolve();audit_path=args.module_audit.resolve()
    if not build.is_relative_to(ROOT/'artifacts') or not audit_path.is_relative_to(ROOT/'artifacts'):p.error('Module/audit must be artifact directories')
    manifest=json.loads((build/'manifest.json').read_text())
    module=build/'usbg_video_a6400_shared_candidate.ko'
    data=module.read_bytes();sha=hashlib.sha256(data).hexdigest()
    if manifest['sha256']!=sha or not manifest['shared_ptp_enumeration_candidate'] or not manifest['start_probe_only']:raise ValueError('Wrong diagnostic module')
    audit=json.loads((audit_path/'manifest.json').read_text())
    if audit['status']!='offline_module_audit_passed' or audit['module_sha256']!=sha:raise ValueError('Audit does not match module')
    out.mkdir(parents=True,exist_ok=False)
    prefix='/tmp_bt/uvc_stop_diag_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    remote=prefix+'.ko';node=prefix+'_video'
    report=dict(status='started',module_sha256=sha,module_path=remote,device=node,files={},
                mode_switch=False,activation=False,native_route_publication=False,camera_writes='/tmp_bt only')
    report['route_shadow_only']=args.route_shadow
    report['entry_hook_cycle']=args.entry_hook
    def save():(out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    def artifact(name,raw):
        (out/name).write_bytes(raw)
        report['files'][name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    def read(dbg,path,name,limit=65536):
        raw,short=dbg.read_all(path,limit);artifact(name,raw)
        if short:raise RuntimeError('Truncated '+path)
        return raw
    def command(dbg,cmd,name):
        result=dbg.request(3,cmd.encode());artifact(name+'.txt',result['payload'])
        report[name]=dict(status=result['status'],flags=result['flags']);save()
        if result['status'] or result['flags']:raise RuntimeError(name+' failed')
    loaded=False;node_created=False;before=None;failure=None;save()
    connections=ExitStack();shared=connections.enter_context(connect())
    try:
        with nullcontext(shared) as dbg:
            artifact('debugger-before.txt',dbg.request(1)['payload'])
            before=read(dbg,'/proc/modules','modules-before.txt')
            if any(line.startswith(b'usbg_video ') for line in before.splitlines()):raise RuntimeError('Module already loaded')
            command(dbg,'test ! -e '+shlex.quote(remote)+' -a ! -e '+shlex.quote(node),'path-check')
            report['upload']=dbg.push(remote,data);save()
            command(dbg,'insmod '+shlex.quote(remote),'insmod');loaded=True
            modules=read(dbg,'/proc/modules','modules-loaded.txt')
            if not any(line.startswith(b'usbg_video ') for line in modules.splitlines()):raise RuntimeError('Loaded module missing')
            command(dbg,'mknod '+shlex.quote(node)+' c 248 33','mknod');node_created=True
        arguments=['--owners',str(args.owners.resolve()),'--probe-build',str(args.probe_build.resolve()),
                     '--attest-device',node,'--output-dir',str(out/'cpu')]
        if args.route_shadow:arguments.append('--route-shadow')
        if args.entry_hook:arguments.append('--entry-hook')
        output=io.StringIO()
        try:
            with redirect_stdout(output):capture_cpu(arguments,debugger=shared)
        finally:artifact('cpu-runner.txt',output.getvalue().encode())
        report['diagnostic']=json.loads((out/'cpu/manifest.json').read_text())['native_stop_diagnostic']
        kernel_path=prefix+'.klog'
        kernel_log=shared.request(3,('test ! -e '+shlex.quote(kernel_path)+' && dmesg > '+shlex.quote(kernel_path)).encode())
        report['kernel_log']=dict(status=kernel_log['status'],flags=kernel_log['flags'],camera_path=kernel_path)
        if not kernel_log['status'] and not kernel_log['flags']:
            read(shared,kernel_path,'kernel-log-after-diagnostic.txt',2*1024*1024)
        else:artifact('kernel-log-read-error.txt',kernel_log['payload'])
        save()
    except Exception as error:
        failure=repr(error);report['error']=failure;save()
    finally:
        with nullcontext(shared) as dbg:
            status=read(dbg,'/proc/149/status','status-final.txt',16384)
            if 'insmod' in report:
                current=read(dbg,'/proc/modules','modules-before-cleanup.txt')
                loaded=any(line.startswith(b'usbg_video ') for line in current.splitlines())
            if not re.search(rb'^TracerPid:\s+0$',status,re.M):
                report['cleanup_error']='Tracer still attached; no module unload attempted'
            else:
                if loaded:
                    try:command(dbg,'rmmod usbg_video','rmmod');loaded=False
                    except Exception as error:report['cleanup_error']=repr(error)
                if not loaded:
                    if node_created:command(dbg,'rm -f '+shlex.quote(node),'remove-node')
                    if 'upload' in report:command(dbg,'rm -f '+shlex.quote(remote),'remove-module-file')
            after=read(dbg,'/proc/modules','modules-after.txt')
            report['module_list_restored']=before is not None and after==before
            artifact('debugger-after.txt',dbg.request(1)['payload'])
            report['status']='idle_stop_diagnostics_passed' if not failure and not loaded and report['module_list_restored'] and 'cleanup_error' not in report else 'failed'
            save()
        connections.close()
    print(json.dumps({k:v for k,v in report.items() if k!='files'},indent=2))
    if report['status']!='idle_stop_diagnostics_passed':raise RuntimeError('Stop diagnostics incomplete; see manifest')


if __name__=='__main__':main()
