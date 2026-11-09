"""Hash-checked offline audit of reference UVC device-node and common ABI."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from tools.research.storage_trace import module_relocations

ROOT=Path(__file__).resolve().parents[2]
A=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev'
Z=ROOT/'firmware/extracted_zve10_v203_linuxnames/firmware.tar_unpacked/0700_part_image/dev'


def checked(path,expected):
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Source hash mismatch: '+str(path))
    return data


def nodes(path):
    with path.open('rb') as stream:
        elf=ELFFile(stream);table=elf.get_section_by_name('.symtab')
        symbol=next(s for s in table.iter_symbols() if s.name=='udif_devnodes')
        section=elf.get_section(symbol['st_shndx']);data=section.data();rel=module_relocations(elf)
        idx=symbol['st_shndx'];result={}
        for off in range(symbol['st_value'],symbol['st_value']+symbol['st_size'],12):
            relocation=rel.get((idx,off))
            if not relocation or relocation['symbol_section']!='.rodata.str1.1':
                raise ValueError('Unexpected device name relocation')
            names=elf.get_section_by_name('.rodata.str1.1').data();start=relocation['target_offset']
            name=names[start:names.index(0,start)].decode('ascii')
            _,kind,number=struct.unpack_from('<III',data,off)
            result[off]={'name':name,'type':kind&65535,'major':kind>>16,
                         'minor':number&65535,'count':number>>16}
        return result


def function(path,name):
    with path.open('rb') as stream:
        elf=ELFFile(stream)
        sym=next(s for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name==name)
        start=sym['st_value'];size=sym['st_size'];index=sym['st_shndx']
        data=bytearray(elf.get_section(index).data()[start:start+size]);rel=[]
        for (sec,off),item in module_relocations(elf).items():
            if sec==index and start<=off<start+size:
                data[off-start:off-start+4]=bytes(4)
                rel.append({'offset':off-start,'type':item['type'],'symbol':item['symbol'],
                            'symbol_section':item['symbol_section']})
        return bytes(data),rel


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args();out=args.report_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):parser.error('Report must remain under artifacts')
    out.mkdir(parents=True,exist_ok=False)
    inventories=[ROOT/'artifacts/inventory/elf-inventory.json',
                 ROOT/'artifacts/analysis/zve10-uvc-bound-e0134/reference-inventory.json']
    expected={r['path']:r['sha256'] for p in inventories for r in json.loads(p.read_text())['entries']}
    baseline=json.loads((ROOT/'artifacts/inventory/baseline.json').read_text())
    expected.update({r['path']:r['sha256'] for r in baseline['inputs']})
    # The complete extraction manifest covers reference initrd devno as well.
    extraction=json.loads((ROOT/'artifacts/analysis/zve10-v203-linuxnames-extraction-e0134/manifest.json').read_text())
    for r in extraction['files']:
        expected[(ROOT/'firmware/extracted_zve10_v203_linuxnames'/r['path']).relative_to(ROOT).as_posix()]=r['sha256']
    inputs=[A/'nflasha3_unpacked/initrd.img_unpacked/kmod/devno.ko',
            Z/'nflasha3_unpacked/initrd.img_unpacked/kmod/devno.ko',
            Z/'nflasha15_unpacked/kmod/usbg_video.ko',A/'nflasha15_unpacked/kmod/usbg_stillimage.ko',
            A/'nflasha3_unpacked/vmlinux.bin',Z/'nflasha3_unpacked/vmlinux.bin']
    for path in inputs:checked(path,expected[path.relative_to(ROOT).as_posix()])
    an,zn=nodes(inputs[0]),nodes(inputs[1])
    with inputs[2].open('rb') as f:
        elf=ELFFile(f)
        refs=[{'section':elf.get_section(sec).name,'offset':off,'target_offset':r['target_offset']}
              for (sec,off),r in module_relocations(elf).items() if r['symbol']=='udif_devnodes']
    if len(refs)!=1 or refs[0]['target_offset']!=0x294:raise ValueError('Video node contract changed')
    offset=refs[0]['target_offset'];functions=[]
    for name in ['usbg_cmn_reg','usbg_cmn_copy_probe_info','usbg_cmn_clear_probe_info','usbg_cmn_clear_ep_list']:
        zcode,zrel=function(inputs[2],name);acode,arel=function(inputs[3],name)
        functions.append({'name':name,'masked_code_equal':zcode==acode,
            'relocation_targets_equal':zrel==arel,'reference_size':len(zcode),'a6400_size':len(acode)})
    kernels=[]
    for model,path in [('a6400',inputs[4]),('zve10',inputs[5])]:
        raw=path.read_bytes();base=0x60108000
        def exported(name):
            at=raw.find(name.encode()+b'\0')
            if at<0:raise ValueError('Kernel export name absent: '+name)
            needle=struct.pack('<I',base+at);hits=[];start=0
            while True:
                pos=raw.find(needle,start)
                if pos<0:break
                value=struct.unpack_from('<I',raw,pos-4)[0] if pos>=4 else 0
                if base<=value<0x60400000 and not value&3:hits.append(value)
                start=pos+4
            if len(hits)!=1:raise ValueError('Ambiguous kernel export: '+name)
            return hits[0]
        address=exported('usb_gadgetcore_register_driver')
        code=raw[address-base:address-base+0x140]
        offsets=[]
        for delta in (0x34,0x40):
            word=struct.unpack_from('<I',code,delta)[0]
            if word&0xfffff000!=0xe5963000:raise ValueError('Unexpected callback guard instruction')
            offsets.append(word&0xfff)
        (out/(model+'-registration-window.bin')).write_bytes(code)
        ep=exported('usb_gadgetcore_is_ep_alive');epcode=raw[ep-base:ep-base+40]
        kernels.append({'model':model,'register_driver':hex(address),'required_callback_offsets':offsets,
                        'window_sha256':hashlib.sha256(code).hexdigest(),
                        'is_ep_alive_address':hex(ep),'is_ep_alive_first_40_sha256':hashlib.sha256(epcode).hexdigest()})
    report={'camera_access':False,'inputs':[{'path':str(p.relative_to(ROOT)),
        'sha256':expected[p.relative_to(ROOT).as_posix()]} for p in inputs],
        'video_node_relocation':refs[0],'reference_node':zn[offset],'a6400_same_offset_node':an[offset],
        'reference_audio_node':zn[0x288],'a6400_same_audio_offset_node':an[0x288],
        'common_functions':functions,'kernel_registration_guards':kernels,'deployable':False,
        'limitations':['Source identity and bounded static ABI comparison only; no module loaded.',
                       'Masked code equality does not prove relocated runtime state or complete ABI compatibility.']}
    (out/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Reference video relocation selects:',zn[offset])
    print('Same offset on a6400 selects:',an[offset])
    for row in functions:print(row['name'],row['masked_code_equal'],row['relocation_targets_equal'])


if __name__=='__main__':main()
