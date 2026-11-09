"""Build an OFFLINE ARM UVC/PTP tree and run Sony's original serializer.

Outputs descriptor fixtures, never a deployable kernel module. Kernel and
reference library identities are checked. No camera connection is made.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_MEM_WRITE, UC_HOOK_CODE, UC_PROT_READ, UC_PROT_EXEC
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.capture_sony_usb_hub import parse_configuration

ROOT=Path(__file__).resolve().parents[2]
KERNEL=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
KERNEL_SHA='12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707'
LIB=ROOT/'firmware/extracted_zve10_v203_linuxnames/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraUsbCmn.so'
LIB_SHA='af830315ce51c38b010995f2147d556286364323734f64b877fcc3bb1a916c02'
SOURCE=ROOT/'tools/native_camera/uvc_ptp_descriptors.c'
HEADER=SOURCE.with_suffix('.h')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    args=parser.parse_args()
    out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):
        parser.error('Output must be under project artifacts')
    out.mkdir(parents=True,exist_ok=True)
    kernel=KERNEL.read_bytes()
    library=LIB.read_bytes()
    if digest(kernel)!=KERNEL_SHA or digest(library)!=LIB_SHA:
        raise ValueError('Original firmware identity mismatch')
    elf_lib=ELFFile(io.BytesIO(library))

    def original_bytes(address,size):
        for segment in elf_lib.iter_segments():
            if segment['p_type']=='PT_LOAD' and segment['p_vaddr']<=address and address+size<=segment['p_vaddr']+segment['p_filesz']:
                offset=segment['p_offset']+address-segment['p_vaddr']
                return library[offset:offset+size]
        raise ValueError('Reference data outside one mapped segment')

    obj=out/'candidate.o'
    target=out/'candidate.elf'
    def run(command):
        if os.name=='nt':
            cwd='/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:]
            command=['wsl.exe','--cd',cwd,'--exec',*command]
        subprocess.run(command,cwd=ROOT,check=True)
    rel=lambda p:p.relative_to(ROOT).as_posix()
    run(['arm-linux-gnueabi-gcc','-std=gnu11','-marm','-march=armv7-a',
         '-mfloat-abi=softfp','-ffreestanding','-fno-builtin',
         '-fno-tree-loop-distribute-patterns','-fno-pic','-fno-pie',
         '-fno-stack-protector','-O2','-Wall','-Wextra','-Werror',
         '-Wno-unused-const-variable','-c',rel(SOURCE),'-o',rel(obj)])
    run(['arm-linux-gnueabi-ld','-Ttext=0x10000','-e',
         'a6400_uvc_ptp_candidate_init','-o',rel(target),rel(obj)])
    binary=target.read_bytes()
    elf=ELFFile(io.BytesIO(binary))
    symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
    unresolved=[s.name for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name and s['st_shndx']=='SHN_UNDEF']
    if unresolved:
        raise ValueError(f'Unresolved candidate imports: {unresolved}')
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    cpu.mem_map(0,0x50000)  # linked PT_LOAD includes ELF headers at VA zero
    for segment in elf.iter_segments():
        if segment['p_type']=='PT_LOAD':
            cpu.mem_write(segment['p_vaddr'],segment.data())
    cpu.mem_map(0x60108000,(len(kernel)+4095)&~4095)
    cpu.mem_write(0x60108000,kernel)
    cpu.mem_protect(0x60108000,(len(kernel)+4095)&~4095,UC_PROT_READ|UC_PROT_EXEC)
    cpu.mem_map(0x200000,0x20000)
    cpu.mem_map(0x400000,0x10000)
    cpu.mem_map(0x500000,0x1000)
    phase=['init']
    stack_low=[0x40f000]
    text=elf.get_section_by_name('.text')
    allowed_code=[(text['sh_addr'],text['sh_addr']+text['sh_size']),
                  (0x602bbc54,0x602bbfec), (0x60258b80,0x60258eb0),
                  (0x602bb988,0x602bba94), (0x602bbfec,0x602bc26c)]
    executed=set()
    serializer_calls=[0]
    def code_guard(machine,address,size,user):
        if address==0x500000: return
        if not any(lo<=address and address+size<=hi for lo,hi in allowed_code):
            raise RuntimeError(f'Execution outside candidate/serializer/memcpy: {address:08x}')
        executed.add(address)
        if address==0x602bbc54:serializer_calls[0]+=1
    cpu.hook_add(UC_HOOK_CODE,code_guard)
    def write_guard(machine,access,address,size,value,user):
        if 0x400000<=address<0x40f000:stack_low[0]=min(stack_low[0],address)
        allowed=[(0x400000,0x410000)]
        if phase[0]=='init': allowed.append((0x200000,0x200400))
        else: allowed.append((0x218000,0x218400))
        if not any(lo<=address and address+size<=hi for lo,hi in allowed):
            raise RuntimeError(f'Unexpected {phase[0]} write {address:08x}/{size}')
    cpu.hook_add(UC_HOOK_MEM_WRITE,write_guard)
    def call(address,*values):
        for register,value in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),values):
            cpu.reg_write(register,value)
        cpu.reg_write(UC_ARM_REG_SP,0x40f000)
        for index,value in enumerate(values[4:]):
            cpu.mem_write(0x40f000+index*4,struct.pack('<I',value))
        cpu.reg_write(UC_ARM_REG_LR,0x500000)
        cpu.emu_start(address,0x500000,count=100000)
        if cpu.reg_read(UC_ARM_REG_PC)!=0x500000:
            raise RuntimeError('Instruction limit before return')
        return cpu.reg_read(UC_ARM_REG_R0)
    checks=[]
    def check(name,value):
        if not value: raise AssertionError(name)
        checks.append(name)
    call(symbols['a6400_uvc_ptp_candidate_init'],0x200000)
    # Minimal explicit gadgetcore fixture: speed=HIGH(3), table=candidate.
    cpu.mem_write(0x210000,struct.pack('<I',0x211000))
    cpu.mem_write(0x211020,struct.pack('<I',3))
    cpu.mem_write(0x21006c,struct.pack('<I',0x200000))
    phase[0]='serializer'
    def serialize(length,kind=2):
        cpu.mem_write(0x212000,struct.pack('<BBHHH',0x80,6,kind<<8,0,length))
        size=call(0x602bbc54,0x210000,0x212000,0x218000,kind)
        if size>0x400: raise RuntimeError(f'Serializer failed {size:08x}')
        return bytes(cpu.mem_read(0x218000,size))
    raw=serialize(1024)
    parsed=parse_configuration(raw)
    check('original-serializer-three-interfaces',len(parsed['interfaces'])==3)
    ptp_report=json.loads((ROOT/'artifacts/hardware/uvc-ptp-coexistence-e0152/pc-remote-hub-descriptors.json').read_text())
    captured=bytes.fromhex(ptp_report['devices'][0]['configurations'][0]['raw_hex'])
    check('physical-ptp-interface-and-endpoints-byte-equal',raw[9:39]==captured[9:])
    check('physical-config-power-and-attributes-preserved',raw[5:9]==captured[5:9])
    check('vc-interface-one',parsed['interfaces'][1]['number']==1 and parsed['interfaces'][1]['class']==14 and parsed['interfaces'][1]['subclass']==1)
    check('vs-interface-two',parsed['interfaces'][2]['number']==2 and parsed['interfaces'][2]['class']==14 and parsed['interfaces'][2]['subclass']==2)
    check('video-endpoint-84',parsed['interfaces'][2]['endpoints']==[dict(address='0x84',attributes=2,max_packet=512,interval=0)])
    # 9 config + 30 PTP + 9 VC = 48; VS follows 40 original VC bytes.
    vc=bytearray(original_bytes(0x12598,40)); vc[12]=2
    vs=bytearray(original_bytes(0x12625,61)); vs[6]=0x84
    check('original-vc-only-interface-reference-remapped',raw[48:88]==vc)
    check('original-vs-only-endpoint-reference-remapped',raw[97:158]==vs)
    check('no-endpoint-address-collision',len({e['address'] for i in parsed['interfaces'] for e in i['endpoints']})==4)
    check('original-header-request-total',serialize(9)==raw[:9])
    check('original-short-request-truncation',serialize(17)==raw[:17])
    check('original-zero-request-truncation',serialize(0)==b'')
    # Candidate postprocessing runs actual compiled ARM, after full Sony
    # serialization and before requested-length truncation. No return stubs.
    phase[0]='iad'
    cpu.mem_write(0x218000,raw)
    size=call(symbols['a6400_uvc_ptp_candidate_add_iad'],0x218000,len(raw),1024)
    final=bytes(cpu.mem_read(0x218000,size))
    check('video-iad-at-interface-boundary',final[39:47]==bytes([8,11,1,2,14,3,0,0]))
    check('iad-preserves-ptp-bytes',final[9:39]==captured[9:])
    check('iad-total-length',struct.unpack_from('<H',final,2)[0]==len(raw)+8)
    check('iad-keeps-three-interfaces',len(parse_configuration(final)['interfaces'])==3)
    for name,data,capacity in [('repeat',final,1024),('capacity',raw,len(raw)+7),
                               ('truncated',raw[:-1],1024),('malformed',raw[:39]+b'\0'+raw[40:],1024)]:
        cpu.mem_write(0x218000,data)
        result=call(symbols['a6400_uvc_ptp_candidate_add_iad'],0x218000,len(data),capacity)
        check('iad-rejects-'+name,result==0xffffffea)
        check('iad-reject-'+name+'-no-mutation',bytes(cpu.mem_read(0x218000,len(data)))==data)
    # End-to-end compiled EP0 reply -> original Sony serializer -> compiled
    # IAD insertion -> requested prefix. No serializer replacement/stub.
    phase[0]='reply'
    candidate_snapshot=bytes(cpu.mem_read(0x200000,1024))
    for requested in (0,1,8,9,17,39,40,47,172,173,174,512,65535):
        setup=struct.pack('<BBHHH',0x80,6,0x0200,0,requested)
        cpu.mem_write(0x212000,setup)
        cpu.mem_write(0x218000,b'\xa5'*1024)
        before=serializer_calls[0]
        size=call(symbols['a6400_uvc_ptp_candidate_config_reply'],0x200000,0x210000,0x212000,0x218000,1024)
        expected=min(requested,len(final))
        check('ep0-reply-length-'+str(requested),size==expected)
        check('ep0-native-serializer-called-'+str(requested),serializer_calls[0]==before+1)
        check('ep0-reply-prefix-'+str(requested),bytes(cpu.mem_read(0x218000,expected))==final[:expected])
        if requested in (9,173):
            (out/('native-ep0-reply-'+str(requested)+'.bin')).write_bytes(bytes(cpu.mem_read(0x218000,expected)))
        check('ep0-output-tail-untouched-'+str(requested),bytes(cpu.mem_read(0x218000+expected,1024-expected))==b'\xa5'*(1024-expected))
        check('ep0-original-request-unchanged-'+str(requested),bytes(cpu.mem_read(0x212000,8))==setup)
        check('ep0-native-tree-unchanged-'+str(requested),bytes(cpu.mem_read(0x200000,1024))==candidate_snapshot)
    config=struct.unpack_from('<I',candidate_snapshot,8)[0]
    groups=struct.unpack('<I',cpu.mem_read(config+4,4))[0]
    alts=[struct.unpack('<I',cpu.mem_read(groups+i*8+4,4))[0] for i in range(3)]
    video_ep=struct.unpack('<I',cpu.mem_read(alts[2]+4,4))[0]
    for name,address,data,capacity,output in [
        ('other-speed',0x212003,b'\x07',1024,0x218000),
        ('wrong-config-index',0x212002,b'\x01',1024,0x218000),
        ('wrong-recipient',0x212000,b'\x81',1024,0x218000),
        ('wrong-request',0x212001,b'\x05',1024,0x218000),
        ('wrong-index',0x212004,b'\x01',1024,0x218000),
        ('insufficient-capacity',0x212006,b'\xad\0',172,0x218000),
        ('foreign-table',0x21006c,struct.pack('<I',0x200100),1024,0x218000),
        ('non-hs-speed',0x211020,struct.pack('<I',5),1024,0x218000),
        ('interface-count',config+2,b'\x04',1024,0x218000),
        ('alternate-count',groups+1,b'\x02',1024,0x218000),
        ('oversized-class-copy',alts[1]+12,struct.pack('<I',65536),1024,0x218000),
        ('endpoint-extra-copy',video_ep+8,struct.pack('<I',65536),1024,0x218000),
        ('output-alias-setup',0x212006,b'\xad\0',1024,0x212000),
        ('output-alias-tree',0x212006,b'\xad\0',1024,0x200000),
    ]:
        cpu.mem_write(0x200000,candidate_snapshot)
        cpu.mem_write(0x21006c,struct.pack('<I',0x200000))
        cpu.mem_write(0x211020,struct.pack('<I',3))
        cpu.mem_write(0x212000,struct.pack('<BBHHH',0x80,6,0x0200,0,173))
        cpu.mem_write(0x218000,b'\xa5'*1024)
        cpu.mem_write(address,data)
        setup_before=bytes(cpu.mem_read(0x212000,8))
        tree_before=bytes(cpu.mem_read(0x200000,1024))
        before=serializer_calls[0]
        value=call(symbols['a6400_uvc_ptp_candidate_config_reply'],0x200000,0x210000,0x212000,output,capacity)
        check('ep0-reject-'+name,value==(0xffffffe4 if name=='insufficient-capacity' else 0xffffffea))
        check('ep0-reject-before-serializer-'+name,serializer_calls[0]==before)
        check('ep0-reject-output-untouched-'+name,bytes(cpu.mem_read(0x218000,1024))==b'\xa5'*1024)
        check('ep0-reject-request-unchanged-'+name,bytes(cpu.mem_read(0x212000,8))==setup_before)
        check('ep0-reject-tree-unchanged-'+name,bytes(cpu.mem_read(0x200000,1024))==tree_before)
    # Full native 88-byte descriptor table and owned string data. Read the
    # actual camera identity rather than inventing serial/manufacturer names.
    identity_path=ROOT/'artifacts/hardware/uvc-ptp-coexistence-e0152/pc-remote-identity-e0158.json'
    identity_report=json.loads(identity_path.read_text())
    identity=identity_report['devices'][0]
    device=bytes.fromhex(identity['device_descriptor_hex'])
    if identity['language_descriptor_hex']!='04030904':
        raise ValueError('Only verified LANGID 0409 is supported')
    string_raw={s['index']:bytes.fromhex(s['raw_hex']) for s in identity['strings'] if s['language']=='0x409'}
    inputs=[device,string_raw[1],string_raw[2],string_raw[3]]
    addresses=[0x214000,0x214100,0x214200,0x214300]
    phase[0]='init'
    for address,data in zip(addresses,inputs):cpu.mem_write(address,data)
    check('native-owned-identity-init',call(symbols['a6400_uvc_ptp_candidate_identity'],0x200000,*addresses)==0)
    owned_identity=bytes(cpu.mem_read(0x200000,1024))
    # Invalidate input storage after init: native serializers must read owned
    # strings, not the caller's capture buffers or a previous device table.
    for address in addresses:cpu.mem_write(address,bytes(128))
    cpu.mem_write(0x210004,struct.pack('<I',0x213000))
    cpu.mem_write(0x213014,struct.pack('<H',device[7]))
    phase[0]='identity'
    expected_device=bytearray(device);expected_device[4:7]=bytes([0xef,2,1])
    for requested in (0,1,8,18,255):
        setup=struct.pack('<BBHHH',0x80,6,0x0100,0,requested)
        cpu.mem_write(0x212000,setup);cpu.mem_write(0x218000,b'\xa5'*1024)
        size=call(0x602bb988,0x210000,0x212000,0x218000)
        check('native-device-length-'+str(requested),size==min(requested,18))
        check('native-device-identity-'+str(requested),bytes(cpu.mem_read(0x218000,size))==expected_device[:size])
        check('native-device-output-bounds-'+str(requested),bytes(cpu.mem_read(0x218000+size,1024-size))==b'\xa5'*(1024-size))
        if requested==18:(out/'native-hs-device-descriptor.bin').write_bytes(bytes(cpu.mem_read(0x218000,size)))
    expected_strings={0:bytes.fromhex(identity['language_descriptor_hex']),**string_raw}
    for index,expected in expected_strings.items():
        for requested in (0,1,len(expected),255):
            cpu.mem_write(0x212000,struct.pack('<BBHHH',0x80,6,0x0300|index,0 if index==0 else 0x409,requested))
            cpu.mem_write(0x218000,b'\xa5'*1024)
            size=call(0x602bc0cc,0x210000,0x212000,0x218000)
            check('native-string-return-'+str(index)+'-'+str(requested),size==min(requested,len(expected)))
            # Original string serializer writes the full descriptor before
            # truncating its return length, so inspect its full output bound.
            check('native-owned-string-'+str(index)+'-'+str(requested),bytes(cpu.mem_read(0x218000,len(expected)))==expected)
            check('native-string-full-output-bound-'+str(index)+'-'+str(requested),bytes(cpu.mem_read(0x218000+len(expected),1024-len(expected)))==b'\xa5'*(1024-len(expected)))
            if requested==255:(out/('native-string-'+str(index)+'.bin')).write_bytes(bytes(cpu.mem_read(0x218000,len(expected))))
    check('owned-identity-stable-through-serializers',bytes(cpu.mem_read(0x200000,1024))==owned_identity)
    cpu.mem_write(0x212000,struct.pack('<BBHHH',0x80,6,0x0200,0,173))
    size=call(symbols['a6400_uvc_ptp_candidate_config_reply'],0x200000,0x210000,0x212000,0x218000,173)
    check('full-table-config-reply-length',size==173)
    check('full-table-config-reply-unchanged',bytes(cpu.mem_read(0x218000,173))==final)
    check('full-table-owned-identity-unchanged',bytes(cpu.mem_read(0x200000,1024))==owned_identity)
    for index,language in [(4,0x409),(1,0x40a),(0xee,0x409)]:
        cpu.mem_write(0x212000,struct.pack('<BBHHH',0x80,6,0x0300|index,language,255))
        cpu.mem_write(0x218000,b'\xa5'*1024)
        value=call(0x602bc0cc,0x210000,0x212000,0x218000)
        check('native-string-reject-'+str(index)+'-'+str(language),value==0xffffffea)
        check('native-string-reject-no-output-'+str(index)+'-'+str(language),bytes(cpu.mem_read(0x218000,1024))==b'\xa5'*1024)
    for name,address,bad in [('device-shape',addresses[0],b'\x11'),
                             ('string-type',addresses[1]+1,b'\x04'),
                             ('string-odd',addresses[2],b'\x05'),
                             ('string-oversize',addresses[3],b'\x44')]:
        phase[0]='init'
        for pointer,data in zip(addresses,inputs):cpu.mem_write(pointer,data)
        cpu.mem_write(address,bad)
        value=call(symbols['a6400_uvc_ptp_candidate_identity'],0x200000,*addresses)
        check('identity-reject-'+name,value==0xffffffea)
        check('identity-reject-no-mutation-'+name,bytes(cpu.mem_read(0x200000,1024))==owned_identity)
    # Bind FS fallback endpoint parameters to the named native a6400 PC Remote
    # group, not a guessed generic PTP descriptor or a different camera model.
    cmn_path=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraUsbCmn.so'
    cmn_raw=cmn_path.read_bytes()
    if digest(cmn_raw)!='5338bafbb545ebc223fac15c9253a41ac9fe49c01fe32c73af40c3fb50eec0a6':
        raise ValueError('a6400 PC Remote descriptor library identity mismatch')
    cmn_elf=ELFFile(io.BytesIO(cmn_raw))
    def cmn_bytes(address,size):
        for segment in cmn_elf.iter_segments():
            if segment['p_type']=='PT_LOAD' and segment['p_vaddr']<=address and address+size<=segment['p_vaddr']+segment['p_filesz']:
                offset=segment['p_offset']+address-segment['p_vaddr']
                return cmn_raw[offset:offset+size]
        raise ValueError('PC Remote profile outside file-backed segment')
    remote=next(s for s in cmn_elf.get_section_by_name('.dynsym').iter_symbols() if s.name=='remotepc_interface_desc')
    check('named-native-pc-remote-profile',remote['st_value']==0x1ae34 and remote['st_size']==24)
    group=cmn_bytes(remote['st_value'],24)
    profile_rows=[]
    for offset,label,alt_expected,ep_expected in [(0,'hs',0x1adf8,0x1ae4c),(8,'fs',0x1ae0c,0x1ae88)]:
        alt=struct.unpack_from('<I',group,offset+4)[0]
        check('original-'+label+'-group-link',group[offset:offset+4]==b'\0\x01\0\0' and alt==alt_expected)
        native_alt=cmn_bytes(alt,20)
        ep=struct.unpack_from('<I',native_alt,4)[0]
        check('original-'+label+'-ptp-class-link',native_alt[:4]==b'\0\x03\0\0' and native_alt[8:11]==bytes([6,1,1]) and ep==ep_expected)
        endpoints=cmn_bytes(ep,60)
        native_ptr=struct.unpack('<I',cpu.mem_read(alts[0]+4,4))[0] if label=='hs' else struct.unpack('<I',cpu.mem_read(0x200010+8,4))[0]
        # FS pointer is obtained from the actual compiled table, then its
        # configuration/interface/alternate objects, without Python offsets.
        if label=='fs':
            cfg=native_ptr
            grp=struct.unpack('<I',cpu.mem_read(cfg+4,4))[0]
            alternate=struct.unpack('<I',cpu.mem_read(grp+4,4))[0]
            native_ptr=struct.unpack('<I',cpu.mem_read(alternate+4,4))[0]
        check('compiled-'+label+'-endpoints-byte-equal-original',bytes(cpu.mem_read(native_ptr,60))==endpoints)
        profile_rows.append(dict(speed=label,group=hex(remote['st_value']+offset),alternate=hex(alt),endpoints=hex(ep),raw_hex=endpoints.hex()))
    fs_wire=bytearray(captured)
    fs_wire[22:24]=b'\x40\0';fs_wire[29:31]=b'\x40\0';fs_wire[38]=10
    qualifier=bytes.fromhex('0a060002ef0201400100')
    phase[0]='unified-reply'
    for speed in (2,3):
        cpu.mem_write(0x211020,struct.pack('<I',speed))
        config_expected=final if speed==3 else bytes(fs_wire)
        other=bytearray(fs_wire if speed==3 else final);other[1]=7
        cases=[('device',1,0,0,bytes(expected_device)),
               ('config',2,0,0,config_expected),('qualifier',6,0,0,qualifier),
               ('other-speed',7,0,0,bytes(other))]
        cases.extend(('string-'+str(index),3,index,0 if index==0 else 0x409,expected)
                     for index,expected in expected_strings.items())
        for name,kind,index,language,expected in cases:
            for requested in (0,9,65535):
                setup=struct.pack('<BBHHH',0x80,6,(kind<<8)|index,language,requested)
                cpu.mem_write(0x212000,setup);cpu.mem_write(0x218000,b'\xa5'*1024)
                size=call(symbols['a6400_uvc_ptp_candidate_descriptor_reply'],0x200000,0x210000,0x212000,0x218000,1024)
                n=min(requested,len(expected));label=str(speed)+'-'+name+'-'+str(requested)
                check('unified-length-'+label,size==n)
                check('unified-original-output-'+label,bytes(cpu.mem_read(0x218000,n))==expected[:n])
                check('unified-output-bound-'+label,bytes(cpu.mem_read(0x218000+n,1024-n))==b'\xa5'*(1024-n))
                check('unified-setup-unchanged-'+label,bytes(cpu.mem_read(0x212000,8))==setup)
                check('unified-owned-table-unchanged-'+label,bytes(cpu.mem_read(0x200000,1024))==owned_identity)
                if requested==65535:(out/('unified-'+str(speed)+'-'+name+'.bin')).write_bytes(bytes(cpu.mem_read(0x218000,n)))
    for name,setup,capacity,speed in [
        ('unsupported-kind',struct.pack('<BBHHH',0x80,6,0x0400,0,9),1024,3),
        ('unsupported-string',struct.pack('<BBHHH',0x80,6,0x0304,0x409,9),1024,3),
        ('unsupported-language',struct.pack('<BBHHH',0x80,6,0x0301,0x40a,9),1024,3),
        ('short-output',struct.pack('<BBHHH',0x80,6,0x0200,0,9),8,3),
        ('unsupported-superspeed',struct.pack('<BBHHH',0x80,6,0x0100,0,18),1024,5),
    ]:
        cpu.mem_write(0x211020,struct.pack('<I',speed));cpu.mem_write(0x212000,setup)
        cpu.mem_write(0x218000,b'\xa5'*1024)
        value=call(symbols['a6400_uvc_ptp_candidate_descriptor_reply'],0x200000,0x210000,0x212000,0x218000,capacity)
        check('unified-reject-'+name,value==(0xffffffe4 if name=='short-output' else 0xffffffea))
        check('unified-reject-no-output-'+name,bytes(cpu.mem_read(0x218000,1024))==b'\xa5'*1024)
    cpu.mem_write(0x211020,struct.pack('<I',3))
    # Explicit independently relocated graph fixture, modeling pointer topology
    # after save_desc_tbl. This is NOT a successful native allocator fixture.
    heap_next=[0x219000]
    def allocate(data):
        address=heap_next[0];heap_next[0]=(address+len(data)+3)&~3
        if heap_next[0]>0x21f000:raise RuntimeError('Clone fixture capacity')
        cpu.mem_write(address,bytes(data));return address
    def clone_config(pointer):
        value=bytearray(cpu.mem_read(pointer,24))
        groups_ptr=struct.unpack_from('<I',value,4)[0]
        groups_value=bytearray(cpu.mem_read(groups_ptr,value[2]*8))
        for i in range(value[2]):
            alternate_ptr=struct.unpack_from('<I',groups_value,i*8+4)[0]
            alternatives=bytearray(cpu.mem_read(alternate_ptr,groups_value[i*8+1]*20))
            for j in range(groups_value[i*8+1]):
                pos=j*20;ep_count=alternatives[pos+1]
                ep_ptr=struct.unpack_from('<I',alternatives,pos+4)[0]
                if ep_count:struct.pack_into('<I',alternatives,pos+4,allocate(cpu.mem_read(ep_ptr,ep_count*20)))
                extra_size=struct.unpack_from('<I',alternatives,pos+12)[0]
                extra_ptr=struct.unpack_from('<I',alternatives,pos+16)[0]
                if extra_size:struct.pack_into('<I',alternatives,pos+16,allocate(cpu.mem_read(extra_ptr,extra_size)))
            struct.pack_into('<I',groups_value,i*8+4,allocate(alternatives))
        struct.pack_into('<I',value,4,allocate(groups_value))
        return allocate(value)
    clone_value=bytearray(cpu.mem_read(0x200000,88))
    for i in (0,1):
        struct.pack_into('<I',clone_value,i*16+8,clone_config(struct.unpack_from('<I',clone_value,i*16+8)[0]))
    language_ptr=struct.unpack_from('<I',clone_value,60)[0]
    language_value=bytearray(cpu.mem_read(language_ptr,8))
    strings_ptr=struct.unpack_from('<I',language_value,4)[0]
    strings_value=bytearray(cpu.mem_read(strings_ptr,24))
    for i in range(3):
        ptr=struct.unpack_from('<I',strings_value,i*8+4)[0]
        struct.pack_into('<I',strings_value,i*8+4,allocate(cpu.mem_read(ptr,strings_value[i*8+1])))
    struct.pack_into('<I',language_value,4,allocate(strings_value))
    clone_language=allocate(language_value)
    struct.pack_into('<I',clone_value,60,clone_language)
    clone=allocate(clone_value)
    clone_snapshot=bytes(cpu.mem_read(0x219000,heap_next[0]-0x219000))
    check('independent-clone-pointer',clone!=0x200000)
    check('independent-clone-valid',call(symbols['a6400_uvc_ptp_validate_native_copy'],0x200000,clone)==0)
    cpu.mem_write(0x21006c,struct.pack('<I',clone))
    for speed in (2,3):
        cpu.mem_write(0x211020,struct.pack('<I',speed))
        for name,kind,index,lang in [('device',1,0,0),('config',2,0,0),
            ('qualifier',6,0,0),('other-speed',7,0,0),('string-3',3,3,0x409)]:
            expected=(out/('unified-'+str(speed)+'-'+name+'.bin')).read_bytes()
            cpu.mem_write(0x212000,struct.pack('<BBHHH',0x80,6,(kind<<8)|index,lang,65535))
            cpu.mem_write(0x218000,b'\xa5'*1024)
            size=call(symbols['a6400_uvc_ptp_candidate_descriptor_reply'],0x200000,0x210000,0x212000,0x218000,1024)
            label=str(speed)+'-'+name
            check('clone-reply-'+label,size==len(expected) and bytes(cpu.mem_read(0x218000,len(expected)))==expected)
            check('clone-graph-not-mutated-'+label,bytes(cpu.mem_read(0x219000,len(clone_snapshot)))==clone_snapshot)
            check('clone-template-not-mutated-'+label,bytes(cpu.mem_read(0x200000,1024))==owned_identity)
    clone_hs_cfg=struct.unpack_from('<I',clone_value,8)[0]
    clone_fs_cfg=struct.unpack_from('<I',clone_value,24)[0]
    clone_hs_groups=struct.unpack('<I',cpu.mem_read(clone_hs_cfg+4,4))[0]
    clone_vc=struct.unpack('<I',cpu.mem_read(clone_hs_groups+12,4))[0]
    clone_vs=struct.unpack('<I',cpu.mem_read(clone_hs_groups+20,4))[0]
    clone_vc_extra=struct.unpack('<I',cpu.mem_read(clone_vc+16,4))[0]
    clone_video=struct.unpack('<I',cpu.mem_read(clone_vs+4,4))[0]
    clone_fs_groups=struct.unpack('<I',cpu.mem_read(clone_fs_cfg+4,4))[0]
    clone_fs_alt=struct.unpack('<I',cpu.mem_read(clone_fs_groups+4,4))[0]
    clone_fs_ep=struct.unpack('<I',cpu.mem_read(clone_fs_alt+4,4))[0]
    clone_string_entries=struct.unpack('<I',cpu.mem_read(clone_language+4,4))[0]
    clone_serial=struct.unpack('<I',cpu.mem_read(clone_string_entries+20,4))[0]
    for name,address,data in [('speed-count',clone+5,b'\x02'),
        ('missing-config',clone+8,bytes(4)),('interface-count',clone_hs_cfg+2,b'\x04'),
        ('wire-index',clone_hs_groups+8,b'\x03'),('endpoint-count',clone_vs+1,b'\x02'),
        ('vc-reference',clone_vc_extra+12,b'\x03'),('video-ptp-collision',clone_video,b'\x81'),
        ('fs-packet-size',clone_fs_ep+2,b'\0\x02'),('serial-content',clone_serial,b'\x00'),
        ('language-id',clone_language,b'\x0a\x04')]:
        cpu.mem_write(0x219000,clone_snapshot);cpu.mem_write(address,data)
        cpu.mem_write(0x218000,b'\xa5'*1024)
        check('clone-reject-'+name,call(symbols['a6400_uvc_ptp_validate_native_copy'],0x200000,clone)==0xffffffea)
        check('clone-reply-reject-'+name,call(symbols['a6400_uvc_ptp_candidate_descriptor_reply'],0x200000,0x210000,0x212000,0x218000,1024)==0xffffffea)
        check('clone-reject-output-unchanged-'+name,bytes(cpu.mem_read(0x218000,1024))==b'\xa5'*1024)
    cpu.mem_write(0x219000,clone_snapshot)
    cpu.mem_write(0x21006c,struct.pack('<I',0x200000))
    cpu.mem_write(0x211020,struct.pack('<I',3))
    (out/'sony-serialized-before-iad.bin').write_bytes(raw)
    (out/'owned-template-fixture.bin').write_bytes(owned_identity)
    (out/'independent-copy-fixture.bin').write_bytes(clone_snapshot)
    (out/'uvc-ptp-hs-config.bin').write_bytes(final)
    report=dict(status='offline_controls_passed',check_count=len(checks),checks=checks,
        executed_pc_count=len(executed),
        observed_fixture_stack_bytes=0x40f000-stack_low[0],
        camera_access=False,deployable=False,kernel_sha256=KERNEL_SHA,reference_library_sha256=LIB_SHA,
        candidate_elf_sha256=digest(binary),source_sha256=digest(SOURCE.read_bytes()),
        identity_capture_sha256=digest(identity_path.read_bytes()),
        original_pc_remote_library_sha256=digest(cmn_raw),original_pc_remote_profiles=profile_rows,
        independent_clone_fixture_bytes=len(clone_snapshot),
        fixture_addresses=dict(template='0x200000',clone=hex(clone),clone_arena='0x219000'),
        fixture_sha256={'owned-template-fixture.bin':digest(owned_identity),
                        'independent-copy-fixture.bin':digest(clone_snapshot)},
        candidate_device_descriptor_hex=expected_device.hex(),
        header_sha256=digest(HEADER.read_bytes()),configuration=parse_configuration(final),
        limitations=['Caller-owned native tree, gadgetcore, speed, request and stack are explicit offline fixtures.',
            'Original Sony make_config_desc and original memcpy run to return, without host replacement.',
            'No endpoint allocation, driver registration, USB enumeration, sensor ownership or PTP commands are proven.',
            'HS shared + FS PTP-only descriptor policy is verified offline; no live Windows binding, callback lifecycle, rollback or SuperSpeed support is claimed.',
            'Independent descriptor clone is an explicit relocated graph fixture, not proof of native allocation/copy/free success.',
            '720p30 is the preserved reference descriptor profile, not a measured sensor capability.'])
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
