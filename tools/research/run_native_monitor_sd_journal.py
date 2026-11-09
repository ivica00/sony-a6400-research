"""Stage or recover one fixed SD-journal write or restart-verify session; physical camera tool."""
import argparse,hashlib,json,re,shlex,time
from pathlib import Path
from tools.camera_debugger import ROOT,connect

JOURNAL_PATH='A:/A6400J.DAT'
JOURNAL_SIZE=64
JOURNAL_IVAL=0xE0235000


def owned_paths(run):
    paths=run['paths'];binary=paths.get('binary','')
    if not re.fullmatch(r'/tmp_bt/mon_sd_\d{8}_\d{6}\.elf',binary):raise ValueError('Unexpected owned binary path')
    prefix=binary[:-4]
    expected={'binary':binary,'log':prefix+'.log','receipt':prefix+'.log.receipt','stdout':prefix+'.stdout','expected':prefix+'.expected'}
    if paths!=expected:raise ValueError('Unexpected owned path set')
    return list(expected.values())


def expected_bytes():
    return b''.join((JOURNAL_IVAL+i).to_bytes(8,'little') for i in range(JOURNAL_SIZE//8))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=['stage','collect','cleanup']);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--mode',choices=['write','verify','probe','idle']);a=p.parse_args()
    out=a.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts/hardware'):p.error('Use artifacts/hardware')
    if a.phase=='stage':
        if not a.mode:p.error('stage requires --mode')
        out.mkdir(parents=True,exist_ok=False)
        build=ROOT/'artifacts/native/monitor-sd-journal-e0238';binary=build/'native_monitor_collector.elf'
        raw=binary.read_bytes();manifest=json.loads((build/'manifest.json').read_text())
        key=binary.relative_to(ROOT).as_posix();digest=hashlib.sha256(raw).hexdigest()
        if digest!=manifest['files'][key]['sha256']:raise RuntimeError('Binary differs from build receipt')
        nonce=time.strftime('%Y%m%d_%H%M%S');prefix='/tmp_bt/mon_sd_'+nonce
        run={'status':'preparing','mode':a.mode,'binary_sha256':digest,'journal':{'path':JOURNAL_PATH,'size':JOURNAL_SIZE,'ival':JOURNAL_IVAL,'expected_sha256':hashlib.sha256(expected_bytes()).hexdigest()},'paths':{'binary':prefix+'.elf','log':prefix+'.log','receipt':prefix+'.log.receipt','stdout':prefix+'.stdout','expected':prefix+'.expected'}}
        def save():(out/'run.json').write_text(json.dumps(run,indent=2)+'\n')
        save()
        with connect() as d:
            status,tr=d.read_all('/proc/149/status',8192);modules,mt=d.read_all('/proc/modules',32768)
            (out/'status-before.txt').write_bytes(status);(out/'modules-before.txt').write_bytes(modules)
            if tr or mt or b'TracerPid:\t0\n' not in status or b'usbg_video ' in modules:raise RuntimeError('Camera not in expected clean state')
            uptime,ut=d.read_all('/proc/uptime',256)
            try:up=float(uptime.split()[0])
            except Exception:raise RuntimeError('Camera uptime unavailable')
            if ut or up<60:raise RuntimeError('Camera boot too recent; wait for a stable boot before staging')
            run['uptime_seconds']=round(up,2)
            check=' && '.join('test ! -e '+shlex.quote(x) for x in run['paths'].values())
            r=d.request(3,check.encode())
            if r['status'] or r['flags']:raise RuntimeError('Fresh RAM paths unavailable')
            run['upload']=d.push(run['paths']['binary'],raw);save()
            q={k:shlex.quote(v) for k,v in run['paths'].items()}
            flag={'write':'--sd-journal','verify':'--sd-journal-verify','probe':'--sd-probe','idle':'--sd-idle'}[a.mode]
            command=f"chmod 700 {q['binary']} && {{ {q['binary']} {q['log']} {flag} > {q['stdout']} 2>&1 < /dev/null & echo $!; }}"
            r=d.request(3,command.encode());(out/'launch.txt').write_bytes(r['payload'])
            if r['status'] or r['flags']:raise RuntimeError('Launch unconfirmed; do not retry')
            run['pid_text']=r['payload'].decode(errors='replace');run['status']='launched_not_yet_ready';save()
            time.sleep(1)
            ready,tr=d.read_all(run['paths']['log'],32768);(out/'ready.log').write_bytes(ready)
            if tr or b'MONITOR_COLLECTOR READY ' not in ready:raise RuntimeError('READY unconfirmed; no mode-switch instruction')
            run['status']='ready_waiting_for_ordinary_pcremote';save()
        print('READY: ordinary PC Remote switch now; no UVC activation. Return MSC after the bounded '+a.mode+' session.')
    elif a.phase=='collect':
        run=json.loads((out/'run.json').read_text())
        with connect() as d:
            for key in ['receipt','stdout','expected']:
                data,tr=d.read_all(run['paths'][key],2*1024*1024)
                (out/(key+'.bin')).write_bytes(data)
                if tr:raise RuntimeError('Truncated '+key+'; retain camera files')
            receipt=(out/'receipt.bin').read_bytes();stdout=(out/'stdout.bin').read_bytes()
            if (b'JOURNAL_SESSION_COMPLETE ' not in receipt and b'PROBE_SESSION_COMPLETE ' not in receipt and b'IDLE_SESSION_COMPLETE ' not in receipt) or b'RECEIPT_VERIFIED ' not in stdout:
                raise RuntimeError('Completion/copy verification absent; retain camera files')
            if (out/'expected.bin').read_bytes()!=expected_bytes():raise RuntimeError('Expected RAM file differs; retain camera files')
            status,tr=d.read_all('/proc/149/status',8192);modules,mt=d.read_all('/proc/modules',32768)
            (out/'status-after.txt').write_bytes(status);(out/'modules-after.txt').write_bytes(modules)
            if tr or mt or b'TracerPid:\t0\n' not in status or b'usbg_video ' in modules:raise RuntimeError('Post-state differs; retain files')
            mode=run['mode']
            if mode=='probe':
                success=b'PROBE_SESSION_COMPLETE steps=3 result=1' in receipt
                run['status']='receipt_recovered_probe_'+('success' if success else 'not_successful')
            elif mode=='idle':
                success=b'IDLE_SESSION_COMPLETE result=1' in receipt
                run['status']='receipt_recovered_idle_'+('success' if success else 'not_successful')
            else:
                steps=7 if mode=='write' else 2
                success=('JOURNAL_SESSION_COMPLETE mode=%s steps=%d result=1'%(mode,steps)).encode() in receipt
                run['status']='receipt_recovered_journal_'+mode+'_'+('success' if success else 'not_successful')
            run['camera_files_retained']=True
            (out/'run.json').write_text(json.dumps(run,indent=2)+'\n')
        print(run['status']+'; camera files retained for separate checked cleanup')
    else:
        run=json.loads((out/'run.json').read_text());paths=owned_paths(run)
        if run['status'] not in ['receipt_recovered_journal_write_success','receipt_recovered_journal_write_not_successful','receipt_recovered_journal_verify_success','receipt_recovered_journal_verify_not_successful','receipt_recovered_probe_success','receipt_recovered_probe_not_successful','receipt_recovered_idle_success','receipt_recovered_idle_not_successful']:raise RuntimeError('Recover and verify receipt before cleanup')
        pid=run['pid_text'].strip()
        if not pid.isascii() or not pid.isdecimal() or not 1<int(pid)<0x7fffffff:raise ValueError('Invalid helper PID')
        with connect() as d:
            r=d.request(3,f'if test -d /proc/{pid}; then echo PRESENT; else echo EXITED; fi'.encode())
            (out/'helper-exit.txt').write_bytes(r['payload'])
            if r['status'] or r['flags'] or r['payload'].strip()!=b'EXITED':raise RuntimeError('Helper exit unverified; retain files')
            for key in ['receipt','stdout','expected']:
                data,tr=d.read_all(run['paths'][key],2*1024*1024)
                if tr or data!=(out/(key+'.bin')).read_bytes():raise RuntimeError('Camera file changed; retain files')
            r=d.request(3,('rm '+ ' '.join(shlex.quote(x) for x in paths)).encode())
            (out/'cleanup.txt').write_bytes(r['payload'])
            if r['status'] or r['flags']:raise RuntimeError('Cleanup unconfirmed')
            r=d.request(3,(' && '.join('test ! -e '+shlex.quote(x) for x in paths)).encode())
            if r['status'] or r['flags']:raise RuntimeError('Owned path remains')
        run.update(status=run['status']+'_cleaned',camera_files_retained=False,helper_exit_verified=True)
        (out/'run.json').write_text(json.dumps(run,indent=2)+'\n');print(run['status'])


if __name__=='__main__':main()
