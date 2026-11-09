"""Build the isolated ARM callback bridge for offline execution only."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--enumeration-only',action='store_true')
    args=parser.parse_args();out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):parser.error('Output must remain under artifacts')
    out.mkdir(parents=True,exist_ok=False)
    source=ROOT/'tools/native_camera/uvc_callback_bridge.c';header=source.with_suffix('.h')
    obj=out/'uvc_callback_bridge.o';elf=out/'uvc_callback_bridge.elf'
    def rel(path):return path.relative_to(ROOT).as_posix()
    def run(tool,args):
        command=[tool,*args]
        if os.name!='posix':command=['wsl.exe','--cd','/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:],'--exec',*command]
        subprocess.run(command,cwd=ROOT,check=True)
    run('arm-linux-gnueabi-gcc',['-std=gnu11','-marm','-march=armv7-a','-mfloat-abi=softfp',
        '-ffreestanding','-fno-builtin','-fno-pic','-fno-pie','-fno-stack-protector',
        '-fno-unwind-tables','-fno-asynchronous-unwind-tables','-ffunction-sections',
        '-O2','-Wall','-Wextra','-Werror',*(['-DA6400_UVC_ENUMERATION_ONLY=1'] if args.enumeration_only else []),'-c',rel(source),'-o',rel(obj)])
    run('arm-linux-gnueabi-ld',['--no-undefined','-e','a6400_uvc_bridge_prepare',
        '-Ttext=0x100000','-Tdata=0x110000','-z','max-page-size=4096','-o',rel(elf),rel(obj)])
    with elf.open('rb') as f:
        image=ELFFile(f)
        unresolved=[s.name for s in image.get_section_by_name('.symtab').iter_symbols()
                    if s.name and s['st_shndx']=='SHN_UNDEF']
        if unresolved:raise ValueError('Unresolved bridge helpers: '+repr(unresolved))
    report={'enumeration_only':args.enumeration_only,'camera_access':False,'deployed':False,'deployable':False,
        'files':{rel(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,header,obj,elf]},
        'unresolved':unresolved,'scope':'Standalone compiled MOD for descriptor/callback contracts.',
        'limitations':['No native registration/unregistration consumer is implemented.',
            'Registration masks must come from actual kernel acknowledgements, not constants.',
            'Endpoint/DMA ABI, quiescence and final module-unload lifetime remain unverified.']}
    (out/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Compiled ARM bridge, no unresolved helpers, OFFLINE/not deployable')


if __name__=='__main__':main()
