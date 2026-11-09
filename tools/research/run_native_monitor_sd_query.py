"""Stage or recover one fixed native SD-info observation; physical camera tool."""
import argparse,hashlib,json,re,shlex,time
from pathlib import Path
from tools.camera_debugger import ROOT,connect


def owned_paths(run):
    paths=run['paths'];binary=paths.get('binary','')
    if not re.fullmatch(r'/tmp_bt/mon_sd_\d{8}_\d{6}\.elf',binary):raise ValueError('Unexpected owned binary path')
    prefix=binary[:-4]
    expected={'binary':binary,'log':prefix+'.log','receipt':prefix+'.log.receipt','stdout':prefix+'.stdout'}
    if paths!=expected:raise ValueError('Unexpected owned path set')
    return list(expected.values())


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['stage','collect','cleanup']);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
    out=a.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts/hardware'):p.error('Use artifacts/hardware')
    if a.phase=='stage':
        out.mkdir(parents=True,exist_ok=False)
        build=ROOT/'artifacts/native/monitor-sd-collector-e0233';binary=build/'native_monitor_collector.elf'
        raw=binary.read_bytes();manifest=json.loads((build/'manifest.json').read_text())
        key=binary.relative_to(ROOT).as_posix();digest=hashlib.sha256(raw).hexdigest()
        if digest!=manifest['files'][key]['sha256']:raise RuntimeError('Binary differs from build receipt')
        nonce=time.strftime('%Y%m%d_%H%M%S');prefix='/tmp_bt/mon_sd_'+nonce
        run={'status':'preparing','binary_sha256':digest,'paths':{'binary':prefix+'.elf','log':prefix+'.log','receipt':prefix+'.log.receipt','stdout':prefix+'.stdout'}}
        def save():(out/'run.json').write_text(json.dumps(run,indent=2)+'\n')
        save()
        with connect() as d:
            status,tr=d.read_all('/proc/149/status',8192);modules,mt=d.read_all('/proc/modules',32768)
            (out/'status-before.txt').write_bytes(status);(out/'modules-before.txt').write_bytes(modules)
            if tr or mt or b'TracerPid:\t0\n' not in status or b'usbg_video ' in modules:raise RuntimeError('Camera not in expected clean state')
            check=' && '.join('test ! -e '+shlex.quote(x) for x in run['paths'].values())
            r=d.request(3,check.encode())
            if r['status'] or r['flags']:raise RuntimeError('Fresh RAM paths unavailable')
            run['upload']=d.push(run['paths']['binary'],raw);save()
            q={k:shlex.quote(v) for k,v in run['paths'].items()}
            command=f"chmod 700 {q['binary']} && {{ {q['binary']} {q['log']} --sd-info > {q['stdout']} 2>&1 < /dev/null & echo $!; }}"
            r=d.request(3,command.encode());(out/'launch.txt').write_bytes(r['payload'])
            if r['status'] or r['flags']:raise RuntimeError('Launch unconfirmed; do not retry')
            run['pid_text']=r['payload'].decode(errors='replace');run['status']='launched_not_yet_ready';save()
            time.sleep(1)
            ready,tr=d.read_all(run['paths']['log'],32768);(out/'ready.log').write_bytes(ready)
            if tr or b'MONITOR_COLLECTOR READY ' not in ready:raise RuntimeError('READY unconfirmed; no mode-switch instruction')
            run['status']='ready_waiting_for_ordinary_pcremote';save()
        print('READY: ordinary PC Remote switch now; no UVC activation. Return MSC after observation to recover receipt.')
    elif a.phase=='collect':
        run=json.loads((out/'run.json').read_text())
        with connect() as d:
            for key in ['receipt','stdout']:
                data,tr=d.read_all(run['paths'][key],32768)
                (out/(key+'.bin')).write_bytes(data)
                if tr:raise RuntimeError('Truncated receipt/output; retain camera files')
            receipt=(out/'receipt.bin').read_bytes();stdout=(out/'stdout.bin').read_bytes()
            if b'SAMPLES_COMPLETE ' not in receipt or b'RECEIPT_VERIFIED ' not in stdout:raise RuntimeError('Completion/copy verification absent; retain camera files')
            status,tr=d.read_all('/proc/149/status',8192);modules,mt=d.read_all('/proc/modules',32768)
            (out/'status-after.txt').write_bytes(status);(out/'modules-after.txt').write_bytes(modules)
            if tr or mt or b'TracerPid:\t0\n' not in status or b'usbg_video ' in modules:raise RuntimeError('Post-state differs; retain files')
            run['status']='receipt_recovered_query_success' if b'query=1 result=1 receipt_pending' in receipt else 'receipt_recovered_query_not_successful'
            run['camera_files_retained']=True
            (out/'run.json').write_text(json.dumps(run,indent=2)+'\n')
        print(run['status']+'; camera files retained for separate checked cleanup')
    else:
        run=json.loads((out/'run.json').read_text());paths=owned_paths(run)
        if run['status'] not in ['receipt_recovered_query_success','receipt_recovered_query_not_successful']:raise RuntimeError('Recover and verify receipt before cleanup')
        pid=run['pid_text'].strip()
        if not pid.isascii() or not pid.isdecimal() or not 1<int(pid)<0x7fffffff:raise ValueError('Invalid helper PID')
        with connect() as d:
            r=d.request(3,f'if test -d /proc/{pid}; then echo PRESENT; else echo EXITED; fi'.encode())
            (out/'helper-exit.txt').write_bytes(r['payload'])
            if r['status'] or r['flags'] or r['payload'].strip()!=b'EXITED':raise RuntimeError('Helper exit unverified; retain files')
            for key in ['receipt','stdout']:
                data,tr=d.read_all(run['paths'][key],32768)
                if tr or data!=(out/(key+'.bin')).read_bytes():raise RuntimeError('Receipt changed; retain files')
            r=d.request(3,('rm '+ ' '.join(shlex.quote(x) for x in paths)).encode())
            (out/'cleanup.txt').write_bytes(r['payload'])
            if r['status'] or r['flags']:raise RuntimeError('Cleanup unconfirmed')
            r=d.request(3,(' && '.join('test ! -e '+shlex.quote(x) for x in paths)).encode())
            if r['status'] or r['flags']:raise RuntimeError('Owned path remains')
        run.update(status=run['status']+'_cleaned',camera_files_retained=False,helper_exit_verified=True)
        (out/'run.json').write_text(json.dumps(run,indent=2)+'\n');print(run['status'])


if __name__=='__main__':main()
