"""One-time Senser bootstrap; later debugger commands use native USB MSC/MTP."""
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'Sony-PMCA-RE'))
from pmca.commands.usb import senserShellCommand
from tools.research.elf_metadata_identity import compare_metadata_only


def deploy(cam):
    destination=ROOT/'artifacts/hardware'/('native-usb-debug-deploy-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    destination.mkdir(parents=True,exist_ok=False)
    previous=cam.readFile('/etc/ld.so.preload')
    (destination/'ld.so.preload.before').write_bytes(previous)
    manifest={'bootstrap_mode':'Senser','operating_transport':'native Sony USB external command',
              'feature':35,'network_listeners':False,'files':{}}
    for name in ('kmod/usb_extcmd.ko','lib/libusbcmd.so'):
        local=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked'/name
        if name=='lib/libusbcmd.so':
            # This exact camera copy was independently compared section by
            # section: all payloads except .comment and every program header
            # match the REA-analyzed library. Pin it, rather than permitting
            # arbitrary repacking or weakening executable-byte identity.
            local=ROOT/'artifacts/hardware/native-usb-debug-deploy-20261105-165840/lib__libusbcmd.so'
            if hashlib.sha256(local.read_bytes()).hexdigest()!='9fbf3339792e40caa73faa63d6b2dfa962ca4c47853320b49ff589595283ba71':
                raise RuntimeError('Validated camera API copy hash changed')
        actual=cam.readFile('/usr/'+name)
        (destination/name.replace('/','__')).write_bytes(actual)
        expected=local.read_bytes()
        manifest.setdefault('original_comparisons',{})[name]={
            'camera_bytes':len(actual),'expected_bytes':len(expected),
            'camera_sha256':hashlib.sha256(actual).hexdigest(),
            'expected_sha256':hashlib.sha256(expected).hexdigest()}
        comparison=compare_metadata_only(actual,expected)
        manifest['original_comparisons'][name]['metadata_identity']=comparison
        if not comparison['equivalent']:
            manifest['state']='stopped_before_payload_upload'
            (destination/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            print(destination)
            raise RuntimeError('Camera driver/API differs from analyzed input: '+name)
        manifest.setdefault('verified_originals',{})[name]=hashlib.sha256(actual).hexdigest()
    for local,remote in [('devcrashday_a6400/a6400_usb_debugd.elf','/setting/a6400_usb_debugd.elf'),
                         ('devcrashday_a6400/hook/usb_debug_launcher.so','/setting/usb_debug_launcher.so')]:
        data=(ROOT/local).read_bytes()
        if len(data)>=32768:
            raise RuntimeError('Payload exceeds verified small-transfer bound')
        cam.writeFile(remote,data)
        if cam.readFile(remote)!=data:
            raise RuntimeError('Upload verification failed; preload unchanged')
        manifest['files'][remote]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'readback_verified':True}
    desired=previous
    if b'/setting/usb_debug_launcher.so' not in previous.split():
        desired=previous.rstrip()+b'\n/setting/usb_debug_launcher.so\n'
    cam.writeFile('/etc/ld.so.preload',desired)
    actual=cam.readFile('/etc/ld.so.preload')
    (destination/'ld.so.preload.after').write_bytes(actual)
    if actual!=desired:
        raise RuntimeError('Preload read-back mismatch')
    manifest['preload_verified']=True
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Uploaded and verified; native USB registration/runtime permissions still need testing.')
    print(destination)


def main():
    state={'completed':False}
    def run(cam):
        deploy(cam)
        state['completed']=True
    senserShellCommand(driverName='libusb',complete=run)
    return 0 if state['completed'] else 2


if __name__=='__main__':
    sys.exit(main())
