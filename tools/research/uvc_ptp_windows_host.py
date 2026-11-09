"""Read-only Sony composite child/driver and SetupAPI observations."""
import argparse, json, os, re, subprocess, time
from datetime import datetime, timezone
from pathlib import Path
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT

SONY=re.compile(r'^USB\\VID_054C&PID_0CAA(?:&REV_[0-9A-F]{4})?(?:&MI_([0-9A-F]{2}))?\\',re.I)


def classify(devices):
    groups=dict(parents=[],ptp_children=[],uvc_children=[],other_interfaces=[])
    for device in devices:
        match=SONY.match(device.get('InstanceId',''))
        if not match:continue
        interface=match[1]
        key='parents' if interface is None else 'ptp_children' if interface.upper()=='00' else 'uvc_children' if interface.upper()=='01' else 'other_interfaces'
        groups[key].append(device)
    def healthy(d):return d.get('Status')=='OK' and d.get('ProblemCode')==0
    def ready(key,service,inf):
        return any(healthy(d) and (str(d.get('Service','')).lower()==service or str(d.get('DriverInf','')).lower()==inf) for d in groups[key])
    groups['composite_parent_ready']=any(healthy(d) and str(d.get('Service','')).lower()=='usbccgp' for d in groups['parents'])
    groups['ptp_ready']=ready('ptp_children','wudfwpdmtp','wpdmtp.inf')
    groups['uvc_ready']=ready('uvc_children','usbvideo','usbvideo.inf')
    groups['children_ready_simultaneously']=all(groups[k] for k in ('composite_parent_ready','ptp_ready','uvc_ready'))
    return groups


def query_devices():
    script=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$items=@(Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -like 'USB\VID_054C&PID_0CAA*'})
$result=@(foreach($d in $items){
  $v=@{};$errors=@()
  foreach($key in @('Service','DriverInfPath','ProblemCode','ProblemStatus','Parent','HardwareIds','CompatibleIds')){
    try{$v[$key]=(Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName ('DEVPKEY_Device_'+$key) -ErrorAction Stop).Data}
    catch{$errors+=($key+': '+$_.Exception.Message)}
  }
  [pscustomobject]@{InstanceId=$d.InstanceId;Status=[string]$d.Status;Class=$d.Class;FriendlyName=$d.FriendlyName;
    Service=$v['Service'];DriverInf=$v['DriverInfPath'];ProblemCode=$v['ProblemCode'];ProblemStatus=$v['ProblemStatus'];Parent=$v['Parent'];
    HardwareIds=$v['HardwareIds'];CompatibleIds=$v['CompatibleIds'];PropertyErrors=$errors}
})
ConvertTo-Json -InputObject $result -Depth 6 -Compress
'''
    result=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script],capture_output=True,timeout=20)
    if result.returncode:raise RuntimeError(result.stderr.decode('utf-8',errors='replace').strip())
    value=json.loads(result.stdout.decode('utf-8-sig'))
    return value if isinstance(value,list) else [value] if value else []


def setupapi_sony():
    path=Path(os.environ.get('SystemRoot','C:/Windows'))/'INF/setupapi.dev.log'
    raw=path.read_bytes()
    encoding='utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-16-le' if b'\0' in raw[:128] else 'utf-8-sig'
    text=raw.decode(encoding,errors='replace')
    blocks=[block for block in re.split(r'(?m)(?=^>>>\s+\[)',text) if 'vid_054c&pid_0caa' in block.lower()]
    return dict(source=str(path),source_bytes=len(raw),matching_blocks=len(blocks)), '\n'.join(blocks)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir',required=True,type=Path)
    p.add_argument('--duration',type=float,default=0,help='0: snapshot; otherwise monitor up to 600 seconds')
    p.add_argument('--interval',type=float,default=2)
    args=p.parse_args()
    if not 0<=args.duration<=600 or not 1<=args.interval<=30:p.error('Invalid bounded monitoring interval/duration')
    out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='observing',driver_changes=False,camera_access=False,samples=[])
    def save():(out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    def setup(name):
        try:
            metadata,text=setupapi_sony();(out/(name+'.txt')).write_text(text,encoding='utf-8');report[name]=metadata
        except OSError as error:report[name]=dict(error=repr(error))
    setup('setupapi-before');start=time.monotonic()
    while True:
        sample=dict(utc=datetime.now(timezone.utc).isoformat(),elapsed_sec=round(time.monotonic()-start,3))
        try:sample.update(classify(query_devices()))
        except Exception as error:sample['query_error']=repr(error)
        report['samples'].append(sample);save()
        remaining=args.duration-(time.monotonic()-start)
        if remaining<=0:break
        time.sleep(min(args.interval,remaining))
    setup('setupapi-after')
    report['status']='observations_complete'
    report['children_ready_observed']=any(s.get('children_ready_simultaneously',False) for s in report['samples'])
    report['limitations']=['PnP binding is not a PTP transaction or decoded UVC sensor frame.',
                           'Parent-only/Error nodes are not successful child bindings; driver errors require SetupAPI analysis.']
    save();print(json.dumps(report,indent=2))


if __name__=='__main__':main()
