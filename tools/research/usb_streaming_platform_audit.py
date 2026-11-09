"""Read-only camera audit of gadget infrastructure and JPEG configuration.

No module loading, configfs mounting, device reads, USB rebinding or camera writes.
"""
import argparse
import gzip
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from elftools.elf.elffile import ELFFile
from tools.camera_debugger import connect

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.report_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):
        parser.error('Report must remain under artifacts')
    out.mkdir(parents=True, exist_ok=False)
    report = {'utc': datetime.now(timezone.utc).isoformat(), 'camera_writes': False,
              'mode_switches': False, 'ptrace': False, 'observations': {}, 'static': {}}

    def flush():
        (out/'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    def retain(name, data, **extra):
        (out/name).write_bytes(data)
        report['observations'][name] = {'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest(), **extra}
        flush()

    commands = {
        'gadget-mounts': 'for p in /sys/kernel/config /config /sys/class/udc /sys/class/android_usb /sys/class/video4linux; do printf "%s\\n" "$p"; ls -ld "$p"; done',
        'gadget-configs': 'for p in /sys/kernel/config/usb_gadget/* /config/usb_gadget/* /sys/class/android_usb/*; do if [ -d "$p" ]; then printf "%s\\n" "$p"; ls "$p"; fi; done',
        'kernel-gadget-modules': 'for p in /usr/kmod/*uvc* /usr/kmod/*video* /usr/kmod/*composite* /usr/kmod/*configfs* /usr/kmod/*gadget* /usr/kmod/*usbg* /usr/kmod/*usb_f*; do if [ -f "$p" ]; then printf "%s\\n" "$p"; fi; done',
        'loaded-gadget-sysfs': 'for p in /sys/module/*uvc* /sys/module/*video* /sys/module/*composite* /sys/module/*configfs* /sys/module/*gadget* /sys/module/*usbg* /sys/module/*usb_f*; do if [ -d "$p" ]; then printf "%s\\n" "$p"; fi; done',
        'udc-attributes': 'for p in /sys/class/udc/*/uevent /sys/class/udc/*/function /sys/class/udc/*/current_speed /sys/class/udc/*/maximum_speed /sys/class/udc/*/state; do if [ -f "$p" ]; then printf "%s\\n" "$p"; while IFS= read -r v; do printf "%s\\n" "$v"; done < "$p"; fi; done',
        'usb-device-nodes': 'for p in /dev/usb/* /dev/video*; do if [ -e "$p" ]; then ls -l "$p"; fi; done',
        'usb-boot-script': 'for p in /usr/bin/usb_insmod.sh /bin/usb_insmod.sh; do if [ -f "$p" ]; then printf "%s\\n" "$p"; while IFS= read -r v; do printf "%s\\n" "$v"; done < "$p"; fi; done',
    }
    with connect() as dbg:
        retain('debug-info.txt', dbg.request(1)['payload'])
        for path, limit in [('/proc/version',4096),('/proc/filesystems',16384),
                            ('/proc/mounts',32768),('/proc/modules',65536),
                            ('/proc/config.gz',256*1024),('/proc/149/maps',256*1024),
                            ('/proc/kallsyms',8*1024*1024)]:
            name = path.strip('/').replace('/','_')
            try:
                data, truncated = dbg.read_all(path, limit)
                retain(name, data, path=path, truncated=truncated)
                if path.endswith('.gz') and not truncated:
                    # Bound decompressed configuration as well as input bytes.
                    import io
                    with gzip.GzipFile(fileobj=io.BytesIO(data)) as packed:
                        unpacked = packed.read(2*1024*1024+1)
                    if len(unpacked)>2*1024*1024:
                        raise ValueError('Kernel configuration exceeds bound')
                    retain('kernel-config.txt',unpacked,source=path)
            except Exception as exc:
                report['observations'][name] = {'path':path,'error':repr(exc)}
                flush()
        for name, command in commands.items():
            try:
                row = dbg.request(3,command.encode())
                retain(name+'.txt',row['payload'],command=command,
                       status=row['status'],flags=row['flags'])
            except Exception as exc:
                report['observations'][name] = {'error':repr(exc)}
                flush()
    inventory=json.loads((ROOT/'artifacts/inventory/elf-inventory.json').read_text())['entries']
    for entry in inventory:
        name=Path(entry['path']).name
        if name not in ('configfs.ko','libcomposite.ko','usb_gadgetcore.ko',
                        'usbg_cmn.ko','usb_darwin.ko','usbg_stillimage.ko',
                        'usb_f_mass_storage.ko','libInfraStreamingServer.so'):
            continue
        path=ROOT/entry['path']; data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=entry['sha256']:
            raise ValueError('Inventory mismatch: '+entry['path'])
        with path.open('rb') as f:
            elf=ELFFile(f)
            symbols=[]
            for section in elf.iter_sections():
                if section['sh_type'] not in ('SHT_SYMTAB','SHT_DYNSYM'):
                    continue
                for s in section.iter_symbols():
                    if re.search(r'uvc|video|gadget|configfs|usb_add|usb_composite|default_width|default_frame|force_backup|compressrate|jpegSizeMax',s.name,re.I):
                        symbols.append({'name':s.name,'value':s['st_value'],
                            'size':s['st_size'],'section':s['st_shndx'],'type':s['st_info']['type']})
            strings=[{'file_offset':m.start(),'text':m.group().decode('ascii')}
                     for m in re.finditer(rb'[ -~]{5,}',data)
                     if re.search(rb'uvc|configfs|gadget|USB Video|VideoStreaming',m.group(),re.I)]
        report['static'][entry['path']]={'sha256':entry['sha256'],'symbols':symbols,'strings':strings}
    report['limitations']=['Absence of a module filename does not exclude built-in functionality.',
        'Read-only, non-atomic MSC observations; no activation, kernel ioctl or encode executed.',
        'Local ELF symbols are inventory-verified, not whole-file matched to camera modules.']
    flush()
    print(out)
    print('retained observations:',len(report['observations']),'local ELF candidates:',len(report['static']))


if __name__=='__main__':
    main()
