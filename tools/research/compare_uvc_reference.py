"""Compare extracted ZV-E10 UVC components against preserved a6400 inputs."""
import argparse
import hashlib
import io
import json
import re
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from tools.research.elf_inventory import inspect_elf

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args();ref=args.reference_root.resolve();out=args.report_dir.resolve()
    if not ref.is_relative_to(ROOT/'firmware') or not out.is_relative_to(ROOT/'artifacts'):
        parser.error('Inputs must be under firmware and reports under artifacts')
    out.mkdir(parents=True,exist_ok=False)
    original=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked'
    report={'reference_root':str(ref),'a6400_root':str(original),'camera_access':False,
            'components':[],'frame_descriptors':[]}
    entries=[]
    for relative in ['kmod/usbg_video.ko','kmod/usbg_audio.ko','kmod/usbg_cmn.ko',
                     'lib/libInfraStreamingUsb.so','lib/libInfraUsbCmn.so','lib/libUsbControl.so']:
        path=ref/relative;raw=path.read_bytes();entries.append(inspect_elf(path))
        names=set();functions=[];modinfo=None
        with path.open('rb') as f:
            elf=ELFFile(f)
            for section in elf.iter_sections():
                if section['sh_type'] in ('SHT_SYMTAB','SHT_DYNSYM'):
                    for symbol in section.iter_symbols():
                        if symbol['st_shndx']!='SHN_UNDEF':names.add(symbol.name)
                        if re.search('uvc|streaming|VideoEsManager',symbol.name,re.I):
                            functions.append({'name':symbol.name,'value':symbol['st_value'],
                                'size':symbol['st_size'],'section':symbol['st_shndx']})
            section=elf.get_section_by_name('.modinfo')
            if section:modinfo=section.data().replace(b'\0',b'\n').decode(errors='replace')
        oldnames=set();old=original/relative
        if old.exists():
            with old.open('rb') as f:
                elf=ELFFile(f)
                for section in elf.iter_sections():
                    if section['sh_type'] in ('SHT_SYMTAB','SHT_DYNSYM'):
                        oldnames.update(s.name for s in section.iter_symbols() if s['st_shndx']!='SHN_UNDEF')
        report['components'].append({'path':relative,'reference_sha256':hashlib.sha256(raw).hexdigest(),
            'bytes':len(raw),'a6400_same_path_exists':old.exists(),
            'a6400_sha256':hashlib.sha256(old.read_bytes()).hexdigest() if old.exists() else None,
            'new_streaming_definitions':[n for n in sorted(names-oldnames) if re.search('uvc|streaming|VideoEsManager',n,re.I)],
            'interesting_symbols':functions,'modinfo':modinfo})
        if relative=='lib/libInfraUsbCmn.so':
            # UVC VS_FRAME_MJPEG descriptors, checked against file bounds
            # and discrete interval count before interpreting their fields.
            for i in range(len(raw)-30):
                n=raw[i]
                if n<30 or raw[i+1:i+3]!=b'\x24\x07' or i+n>len(raw):continue
                b=raw[i:i+n];count=b[25]
                if not count or n!=26+4*count:continue
                width,height=struct.unpack_from('<HH',b,5)
                if not 1<=width<=8192 or not 1<=height<=8192:continue
                intervals=list(struct.unpack_from('<'+'I'*count,b,26))
                report['frame_descriptors'].append({'library':relative,'file_offset':i,
                    'width':width,'height':height,'default_interval_100ns':struct.unpack_from('<I',b,21)[0],
                    'intervals_100ns':intervals,'raw_max_frame_buffer':struct.unpack_from('<I',b,17)[0],
                    'descriptor_hex':b.hex()})
            # Join descriptor bytes to the exported PAL/NTSC interface tables.
            elf=ELFFile(io.BytesIO(raw))
            def mapped(address,size):
                segments=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD'
                    and s['p_vaddr']<=address and address+size<=s['p_vaddr']+s['p_filesz']]
                if len(segments)!=1:raise ValueError('Ambiguous descriptor mapping')
                s=segments[0];offset=address-s['p_vaddr']+s['p_offset']
                return offset,raw[offset:offset+size]
            bindings=[]
            symbols={s.name:s for s in elf.get_section_by_name('.dynsym').iter_symbols()}
            for name in ('streaming_pal_interface_desc','streaming_ntsc_interface_desc'):
                symbol=symbols[name];_,table=mapped(symbol['st_value'],symbol['st_size'])
                for i in range(0,len(table),8):
                    node=struct.unpack_from('<I',table,i+4)[0]
                    _,data=mapped(node,20);words=struct.unpack('<5I',data)
                    if words[2]!=0x20e:continue
                    offset,blob=mapped(words[4],words[3])
                    frames=[f['file_offset'] for f in report['frame_descriptors']
                            if offset<=f['file_offset'] and f['file_offset']+len(bytes.fromhex(f['descriptor_hex']))<=offset+len(blob)]
                    bindings.append({'table':name,'node_linked':node,'blob_linked':words[4],
                        'blob_bytes':words[3],'frame_file_offsets':frames})
            report['descriptor_bindings']=bindings
    report['limitations']=['Static original reference bytes; no module installation or camera execution.',
        'Matching vermagic does not prove cross-camera ABI, ownership or endpoint compatibility.',
        'Descriptor fields advertise formats and limits, not observed frame delivery or allocated capacity.']
    (out/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'reference-inventory.json').write_text(json.dumps({'entries':entries},indent=2),encoding='utf-8')
    print('Reference components:',len(entries),'UVC MJPEG frame descriptors:',len(report['frame_descriptors']))
    for row in report['frame_descriptors']:print(row['width'],row['height'],row['intervals_100ns'])


if __name__=='__main__':main()
