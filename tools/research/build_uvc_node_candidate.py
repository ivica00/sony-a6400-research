"""Build an OFFLINE node-only UVC port object, never an installable module.

Preserves reference executable sections and redirects its sole device-table
import to explicit MOD storage. Callback/endpoint ABI remains unsupported.
"""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from elftools.elf.elffile import ELFFile

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'firmware/extracted_zve10_v203_linuxnames/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/usbg_video.ko'
SHA='d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):parser.error('Output must remain under artifacts')
    if digest(SOURCE)!=SHA:raise ValueError('Reference module identity mismatch')
    from tools.research.uvc_portability_audit import nodes,A
    original_nodes=nodes(A/'nflasha3_unpacked/initrd.img_unpacked/kmod/devno.ko')
    if any(n['major']==248 and n['minor']<=33<n['minor']+n['count'] for n in original_nodes.values()):
        raise ValueError('Proposed node conflicts with preserved a6400 device table')
    out.mkdir(parents=True,exist_ok=False)
    shim=ROOT/'tools/native_camera/uvc_reference_node_shim.c'
    rewritten=out/'reference.rebound.o';compiled=out/'node-shim.o'
    linked=out/'usbg_video.node-only.offline.o'
    def relative(path):return path.relative_to(ROOT).as_posix()
    def run(tool,args):
        command=[tool,*args]
        if os.name!='posix':
            linux='/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:]
            command=['wsl.exe','--cd',linux,'--exec',*command]
        subprocess.run(command,cwd=ROOT,check=True)
    run('arm-linux-gnueabi-objcopy',['--redefine-sym','udif_devnodes=a6400_uvc_devnodes',relative(SOURCE),relative(rewritten)])
    run('arm-linux-gnueabi-gcc',['-std=gnu11','-marm','-march=armv7-a','-mfloat-abi=softfp',
        '-ffreestanding','-fno-pic','-fno-pie','-fno-stack-protector','-O2','-Wall','-Wextra','-Werror',
        '-c',relative(shim),'-o',relative(compiled)])
    run('arm-linux-gnueabi-ld',['-r','-o',relative(linked),relative(rewritten),relative(compiled)])
    run('arm-linux-gnueabi-objcopy',['--localize-symbol=a6400_uvc_devnodes',relative(linked)])
    with SOURCE.open('rb') as a,linked.open('rb') as b:
        original,modified=ELFFile(a),ELFFile(b)
        sections={}
        for s in original.iter_sections():
            if s['sh_flags']&4:
                candidate=modified.get_section_by_name(s.name)
                equal=candidate is not None and candidate.data()==s.data()
                sections[s.name]={'source_sha256':hashlib.sha256(s.data()).hexdigest(),'exact_equal':equal}
                if not equal:raise ValueError('Executable reference section changed: '+s.name)
        symbols=list(modified.get_section_by_name('.symtab').iter_symbols())
        node=[s for s in symbols if s.name=='a6400_uvc_devnodes']
        if len(node)!=1 or node[0]['st_shndx']=='SHN_UNDEF' or node[0]['st_info']['bind']!='STB_LOCAL':
            raise ValueError('Node shim is not privately resolved')
        if any(s.name=='udif_devnodes' and s['st_shndx']=='SHN_UNDEF' for s in symbols):
            raise ValueError('Original kernel table dependency remains')
        import struct
        s=node[0];offset=s['st_value']+0x294;data=modified.get_section(s['st_shndx']).data()
        _,major,minor=struct.unpack_from('<III',data,offset)
        if (major,minor)!=(248<<16,(1<<16)|33):raise ValueError('Private device tuple changed')
    report={'deployed':False,'deployable':False,'camera_access':False,'reference_sha256':SHA,
        'files':{relative(p):digest(p) for p in [SOURCE,shim,compiled,rewritten,linked]},
        'executable_sections':sections,'private_node':{'name':'usb/video','major':248,'minor':33,'count':1,
                                                     'unused_in_preserved_a6400_devno':True},
        'remaining_blockers':['Gadget callback descriptor layout differs between camera kernels.',
            'Callback arguments, endpoint operations, DMA, cache and rollback not verified.',
            'Userland UVC integration and JPEG receiver compatibility not implemented.'],
        'warning':'OFFLINE relocation experiment only. Do not insmod or deploy this object.'}
    (out/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Built OFFLINE node-only object; deployable=False; executable reference sections unchanged')


if __name__=='__main__':main()
