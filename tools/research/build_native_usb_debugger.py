"""Build against the existing Sony libc using the installed WSL ARM compiler."""
import subprocess
import os
import hashlib
import json
from pathlib import Path
from datetime import datetime

ROOT=Path(__file__).resolve().parents[2]


def main():
    if os.name=='posix':
        compiler=['arm-linux-gnueabi-gcc']
    else:
        linux_root='/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:]
        compiler=['wsl.exe','--cd',linux_root,'--exec','arm-linux-gnueabi-gcc']
    common=['-std=gnu11','-march=armv7-a','-mfloat-abi=softfp','-O2','-Wall','-Wextra','-Werror',
            '-nostdlib','-U_FORTIFY_SOURCE','-D_FORTIFY_SOURCE=0','-U_TIME_BITS','-D_TIME_BITS=32',
            '-U_FILE_OFFSET_BITS','-D_FILE_OFFSET_BITS=32']
    executable='devcrashday_a6400/a6400_usb_debugd.elf'
    launcher='devcrashday_a6400/hook/usb_debug_launcher.so'
    (ROOT / executable).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / launcher).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(compiler+common+['-fno-stack-protector',
        '-Wl,-e,_start,-z,defs,-z,max-page-size=4096,--dynamic-linker=/lib/ld-linux.so.3',
        '-o',executable,'tools/native_camera/debug_start.S','tools/native_camera/a6400_usb_debugd.c',
        'tools/sony_sysroot/lib/libc.so','-lgcc'],check=True,cwd=ROOT)
    subprocess.run(compiler+common+['-fPIC','-shared',
        '-Wl,-soname,usb_debug_launcher.so,-z,defs,-z,max-page-size=4096',
        '-o',launcher,'tools/native_camera/hook/usb_debug_launcher.c','tools/sony_sysroot/lib/libc.so'],check=True,cwd=ROOT)
    paths=[executable,launcher,'tools/native_camera/a6400_usb_debugd.c',
           'tools/native_camera/hook/usb_debug_launcher.c','tools/native_camera/debug_start.S',
           'tools/sony_sysroot/lib/libc.so']
    manifest={'deployed':False,'files':{}}
    for path in paths:
        data=(ROOT/path).read_bytes()
        manifest['files'][path]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    destination=ROOT/'artifacts/analysis'/('native-usb-debugger-build-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
    destination.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(destination)


if __name__=='__main__': main()
