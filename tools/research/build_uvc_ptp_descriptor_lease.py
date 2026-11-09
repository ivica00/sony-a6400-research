"""Compiled ARM ownership transaction tests. Save/free are explicit recorders.

An additional original save_desc_tbl entry run stops before copy/allocator
services. No camera access or successful native allocation is claimed.
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
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE,UC_PROT_READ,UC_PROT_EXEC
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC,UC_CPU_ARM_CORTEX_A9
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT,KERNEL,KERNEL_SHA


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--session',action='store_true',help='Also compile and test the orchestration candidate with explicit hardware-operation recorders')
    parser.add_argument('--native-backend',action='store_true',help='Compile guarded native wrappers; kernel/hardware service boundaries remain explicit test doubles')
    args=parser.parse_args();out=args.output_dir.resolve()
    if args.native_backend:args.session=True
    if not out.is_relative_to(ROOT/'artifacts'):parser.error('Output must be under artifacts')
    out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'tools/native_camera/uvc_ptp_descriptors.c',ROOT/'tools/native_camera/uvc_ptp_descriptor_lease.c']
    if args.session:
        sources.extend(ROOT/('tools/native_camera/'+name+'.c') for name in ['uvc_callback_bridge','uvc_ptp_adapter','uvc_ptp_session'])
        fixture=out/'session_probe.c'
        fixture_text='#include "uvc_ptp_session.h"\nvoid probe_inflight(struct a6400_uvc_ptp_session *s,unsigned int n){s->bridge.in_flight=n;}\nstruct uvc_bridge *probe_bridge(struct a6400_uvc_ptp_session *s){return &s->bridge;}\nint probe_stop(struct a6400_uvc_ptp_session *s){return a6400_uvc_bridge_quiesce(&s->bridge);}\n'
        if args.native_backend:
            fixture_text+='unsigned int cpu_cache[16]={0,0,0,0,0x60119de4u};\nstatic const unsigned int mask=15;\nconst unsigned int *cpu_online_mask=&mask;\nunsigned int nr_cpu_ids=4;\nint on_each_cpu(void (*fn)(void *),void *info,int wait){ (void)fn;(void)wait;*(volatile unsigned int *)info=15;*((volatile int *)info+1)=0;return 0; }\nint printk(const char *fmt,...){ (void)fmt;return 0; }\n'
        fixture.write_text(fixture_text,encoding='utf-8')
        sources.append(fixture)
    if args.native_backend:
        sources.append(ROOT/'tools/native_camera/uvc_ptp_code_sync.c')
        sources.append(ROOT/'tools/native_camera/uvc_ptp_native_backend.c')
    def run(command):
        if os.name=='nt':command=['wsl.exe','--cd','/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:],'--exec',*command]
        subprocess.run(command,cwd=ROOT,check=True)
    rel=lambda p:p.relative_to(ROOT).as_posix()
    objects=[]
    for source in sources:
        obj=out/(source.stem+'.o');objects.append(obj)
        run(['arm-linux-gnueabi-gcc','-std=gnu11','-marm','-march=armv7-a','-mfloat-abi=softfp',
             '-ffreestanding','-fno-builtin','-fno-tree-loop-distribute-patterns','-fno-pic','-fno-pie',
             '-fno-stack-protector','-O2','-Wall','-Wextra','-Werror','-Wno-unused-const-variable',
             '-Itools/native_camera',
             '-c',rel(source),'-o',rel(obj)])
    target=out/'descriptor-lease.elf'
    location=['-Ttext=0x5f800000','-Tdata=0x5f810000','-z','max-page-size=4096'] if args.native_backend else ['-Ttext=0x10000']
    run(['arm-linux-gnueabi-ld','--no-undefined',*location,'-e','a6400_descriptor_install',
         '-o',rel(target),*[rel(obj) for obj in objects]])
    inputs=json.loads((args.input_dir/'manifest.json').read_text())
    template=(args.input_dir/'owned-template-fixture.bin').read_bytes()
    clone_data=(args.input_dir/'independent-copy-fixture.bin').read_bytes()
    for name,data in [('owned-template-fixture.bin',template),('independent-copy-fixture.bin',clone_data)]:
        if hashlib.sha256(data).hexdigest()!=inputs['fixture_sha256'][name]:raise ValueError('Descriptor fixture identity mismatch')
    if inputs['source_sha256']!=hashlib.sha256(sources[0].read_bytes()).hexdigest() or inputs['header_sha256']!=hashlib.sha256(sources[0].with_suffix('.h').read_bytes()).hexdigest():
        raise ValueError('Descriptor source no longer matches validated input')
    if inputs['fixture_addresses']['template']!='0x200000' or inputs['fixture_addresses']['clone_arena']!='0x219000':
        raise ValueError('Unexpected fixture mapping')
    clone=int(inputs['fixture_addresses']['clone'],0)
    binary=target.read_bytes();elf=ELFFile(io.BytesIO(binary))
    symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
    kernel=KERNEL.read_bytes()
    if hashlib.sha256(kernel).hexdigest()!=KERNEL_SHA:raise ValueError('Original kernel identity mismatch')
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A9);cpu.mem_map(0,0x50000)
    pages=set()
    for segment in elf.iter_segments():
        if segment['p_type']=='PT_LOAD' and segment['p_vaddr']>=0x50000:
            for page in range(segment['p_vaddr']&~4095,(segment['p_vaddr']+segment['p_memsz']+4095)&~4095,4096):
                if page not in pages:cpu.mem_map(page,4096);pages.add(page)
    for segment in elf.iter_segments():
        if segment['p_type']=='PT_LOAD':cpu.mem_write(segment['p_vaddr'],segment.data())
    cpu.mem_map(0x200000,0x20000);cpu.mem_map(0x400000,0x10000)
    cpu.mem_map(0x500000,0x1000);cpu.mem_map(0x600000,0x1000)
    for a in range(0x600000,0x600b00,0x100):cpu.mem_write(a,bytes.fromhex('1eff2fe1'))
    cpu.mem_map(0x60108000,(len(kernel)+4095)&~4095);cpu.mem_write(0x60108000,kernel)
    cpu.mem_protect(0x60108000,(len(kernel)+4095)&~4095,UC_PROT_READ|UC_PROT_EXEC)
    if args.native_backend and 0x6051b000>=0x60108000+((len(kernel)+4095)&~4095):
        cpu.mem_map(0x6051b000,4096) # explicit live-BSS global-pointer fixture
    TEMPLATE,LEASE,ARG,OPS,OLD,GC=0x200000,0x200800,0x200c00,0x200d00,0x208000,0x210000
    scenario=['success'];events=[];native_run=[False];native_stopped=[False]
    word=lambda address:struct.unpack('<I',cpu.mem_read(address,4))[0]
    put=lambda address,value:cpu.mem_write(address,struct.pack('<I',value))
    text=elf.get_section_by_name('.text')
    writable=[(s['p_vaddr'],s['p_vaddr']+s['p_memsz']) for s in elf.iter_segments() if s['p_type']=='PT_LOAD' and s['p_flags']&2]
    op_counts={}
    descriptor_run=[False]
    backend_run=[False];extra_stop=[None];gcw=[1];native_fault=[''];registry=set();registry_next=[0x206000]
    sites=[0x602b958c,0x602b95ac,0x602b95cc,0x602b95e0]
    def hook(machine,pc,size,user):
        if pc==0x500000:machine.emu_stop();return
        if extra_stop[0] and pc==extra_stop[0]:machine.emu_stop();return
        if pc==0x60119de4:
            events.append(dict(kind='native-sync-cache',arg0=machine.reg_read(UC_ARM_REG_R0),arg1=machine.reg_read(UC_ARM_REG_R1)))
            machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
        if backend_run[0]:
            names={0x602bd450:'native-state',0x602bd834:'native-stop',0x602bd7f8:'native-start',
                   0x602b9464:'native-disconnect',0x602b8610:'native-reg',0x602b8560:'native-unreg',
                   0x602bc550:'native-save',0x602bc3e4:'native-free',0x602b05fc:'native-enable-ep0',
                   0x602b2b40:'native-arm-ep0',0x60119c80:'native-flush',0x602b1d3c:'native-pullup'}
            if pc in names:
                name=names[pc];r0=machine.reg_read(UC_ARM_REG_R0);r1=machine.reg_read(UC_ARM_REG_R1)
                event=dict(kind=name,arg0=r0,arg1=r1);events.append(event);result=0
                if name=='native-state':result=gcw[0]
                elif name=='native-stop':gcw[0]=1
                elif name=='native-start':gcw[0]=3 if r0 else 2
                elif name=='native-disconnect':
                    cpu.mem_write(GC+0x74,b'\0');result=0xdeadbeef # void residual must be ignored
                    node=word(GC+0x78)
                    while node!=GC+0x78:
                        cpu.mem_write(node-4+0x14,b'\0');node=word(node)
                elif name=='native-reg':
                    event['flags']=word(GC+0x68);registry.add(r0)
                    record=registry_next[0];registry_next[0]+=0x40
                    previous=word(GC+0x7c);put(record,r0);put(record+4,GC+0x78);put(record+8,previous)
                    cpu.mem_write(record+0x14,b'\0');put(previous,record+4);put(GC+0x7c,record+4)
                elif name=='native-unreg':
                    event['flags']=word(GC+0x68)
                    if native_fault[0]=='unreg-error':result=0xfffffff0
                    else:
                        registry.discard(r0);node=word(GC+0x78)
                        while node!=GC+0x78:
                            next_node=word(node)
                            if word(node-4)==r0:
                                previous=word(node+4);put(previous,next_node);put(next_node+4,previous)
                            node=next_node
                elif name=='native-save':
                    event['address_limit']=word(0x40e008);event['root_before']=word(GC+0x6c)
                    if native_fault[0]=='save-error':result=0xfffffff4;put(GC+0x6c,0)
                    else:put(GC+0x6c,clone);cpu.mem_write(GC+0x84,b'\0\1')
                elif name=='native-free':event['root_before']=word(GC+0x6c);put(GC+0x6c,0)
                elif name=='native-pullup' and r1==1 and native_fault[0]=='pullup-up':result=0xfffffffb
                machine.reg_write(UC_ARM_REG_R0,result)
                machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR))
                return
        if native_run[0] and pc==0x602bc598:
            native_stopped[0]=True;machine.emu_stop();return
        if pc==0x600000:
            events.append(dict(kind='save_recorder',root_before=word(GC+0x6c),argument=machine.reg_read(UC_ARM_REG_R1)))
            put(GC+0x68,0x80000020);cpu.mem_write(GC+0x84,b'\0\x01')
            name=scenario[0]
            if name in ('native-failure','null-success'):new=0
            elif name=='old-alias':new=OLD
            elif name=='source-alias':new=TEMPLATE
            else:new=clone
            put(GC+0x6c,new)
            if name=='corrupt-clone':cpu.mem_write(clone+2,b'\x00')
            machine.reg_write(UC_ARM_REG_R0,0xfffffff4 if name in ('native-failure','failure-left-root') else 0)
            return
        if pc in (0x600100,0x600200):
            events.append(dict(kind='free_recorder',root_before=word(GC+0x6c)))
            if scenario[0]!='free-left-root':put(GC+0x6c,0)
            return
        if args.session and 0x600300<=pc<=0x600900 and pc%256==0:
            name={0x600300:'quiesce',0x600400:'resume',0x600500:'bind',0x600600:'unbind',
                  0x600700:'reg',0x600800:'unreg',0x600900:'reference-recorder'}[pc]
            op_counts[name]=op_counts.get(name,0)+1
            event=dict(kind=name)
            if name=='reference-recorder':
                event['arguments']=[machine.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
                if event['arguments'][2]==1 and 0x400000<=event['arguments'][3]<0x410000:
                    event['endpoint_wrapper']=word(event['arguments'][3])
            if name in ('reg','unreg'):event['wire']=cpu.mem_read(machine.reg_read(UC_ARM_REG_R0)+5,1)[0]
            events.append(event)
            fail=(scenario[0]=='quiesce' and name=='quiesce' and op_counts[name]==1 or
                  scenario[0]=='reg-2' and name=='reg' and op_counts[name]==2 or
                  scenario[0]=='bind' and name=='bind' or scenario[0]=='unbind' and name=='unbind' or
                  scenario[0]=='resume-shared' and name=='resume' and op_counts[name]==1 or
                  scenario[0]=='resume-old' and name=='resume' and op_counts[name]==2)
            machine.reg_write(UC_ARM_REG_R0,0xfffffffb if fail else 0)
            return
        if text['sh_addr']<=pc<text['sh_addr']+text['sh_size']:return
        if descriptor_run[0] and any(a<=pc<b for a,b in [(0x602bb988,0x602bba94),(0x602bbc54,0x602bc26c),(0x60258b80,0x60258eb0)]):return
        if backend_run[0] and pc in sites:return
        if native_run[0] and 0x602bc550<=pc<0x602bc598:return
        raise RuntimeError(f'Unexpected execution {pc:08x}')
    def write_guard(machine,access,address,size,value,user):
        if any(lo<=address and address+size<=hi for lo,hi in
               [(LEASE,LEASE+64),(GC,GC+0x100),(0x400000,0x410000),
                (0x201000,0x20103c),(0x202000,0x203000),(0x218000,0x218400),*writable]):return
        if args.native_backend and (0x203000<=address and address+size<=0x204100 or
            address==0x211190 and size==4 or address in sites and size==4):return
        raise RuntimeError(f'Unexpected write {address:08x}/{size}')
    cpu.hook_add(UC_HOOK_CODE,hook);cpu.hook_add(UC_HOOK_MEM_WRITE,write_guard)
    def call(name,*values):
        for register,value in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),values):cpu.reg_write(register,value)
        cpu.reg_write(UC_ARM_REG_SP,0x40f000);cpu.reg_write(UC_ARM_REG_LR,0x500000)
        for index,value in enumerate(values[4:]):put(0x40f000+index*4,value)
        cpu.emu_start(symbols[name],0xffffffff,count=100000)
        if cpu.reg_read(UC_ARM_REG_PC)!=0x500000 and cpu.reg_read(UC_ARM_REG_PC)!=extra_stop[0] and not native_stopped[0]:raise RuntimeError('Missing bounded return')
        return cpu.reg_read(UC_ARM_REG_R0)
    def reset(name='success'):
        scenario[0]=name;events.clear();native_run[0]=False;native_stopped[0]=False
        cpu.mem_write(TEMPLATE,template);cpu.mem_write(0x219000,clone_data)
        cpu.mem_write(LEASE,bytes(64));cpu.mem_write(OLD,b'\x5a'*88)
        cpu.mem_write(GC,bytes(0x100));put(GC+0x68,0x80000004);put(GC+0x6c,OLD)
        put(GC,0x211000);put(GC+4,0x213000);put(0x211020,3);cpu.mem_write(0x213014,b'\x40\0')
        cpu.mem_write(GC+0x84,b'\x01\x01')
        cpu.mem_write(ARG,struct.pack('<IIBBBB',TEMPLATE,0,0,0,1,0))
        cpu.mem_write(OPS,struct.pack('<II',0x600000,0x600100))
    checks=[]
    def check(name,value):
        if not value:raise AssertionError(name)
        checks.append(name)
    def restored(label):
        check(label+'-original-root',word(GC+0x6c)==OLD)
        check(label+'-original-flags',word(GC+0x68)==0x80000004)
        check(label+'-original-mode',bytes(cpu.mem_read(GC+0x84,2))==b'\x01\x01')
        check(label+'-source-releasable',call('a6400_descriptor_source_releasable',LEASE)==1)
        check(label+'-old-table-not-freed',bytes(cpu.mem_read(OLD,88))==b'\x5a'*88 and all(e.get('root_before')!=OLD for e in events))
    for cycle in (1,2):
        if cycle==1:reset()
        check('install-'+str(cycle),call('a6400_descriptor_install',LEASE,GC,ARG,OPS)==0)
        check('old-root-hidden-from-save-'+str(cycle),events[-1]['kind']=='save_recorder' and events[-1]['root_before']==0)
        check('installed-root-'+str(cycle),word(GC+0x6c)==clone and word(LEASE)==2)
        check('source-pinned-'+str(cycle),call('a6400_descriptor_source_releasable',LEASE)==0)
        before=len(events);check('duplicate-install-'+str(cycle),call('a6400_descriptor_install',LEASE,GC,ARG,OPS)==0xfffffff0 and len(events)==before)
        check('restore-'+str(cycle),call('a6400_descriptor_restore',LEASE,OPS)==0)
        check('only-installed-copy-freed-'+str(cycle),events[-1]==dict(kind='free_recorder',root_before=clone))
        restored('cycle-'+str(cycle))
    before=len(events);check('repeat-restore-idempotent',call('a6400_descriptor_restore',LEASE,OPS)==0 and len(events)==before)
    for name,error in [('native-failure',0xfffffff4),('null-success',0xfffffffb)]:
        reset(name);check(name+'-error',call('a6400_descriptor_install',LEASE,GC,ARG,OPS)==error)
        check(name+'-no-extra-free',len(events)==1);restored(name)
    for name in ('failure-left-root','old-alias','source-alias','corrupt-clone'):
        reset(name);value=call('a6400_descriptor_install',LEASE,GC,ARG,OPS)
        check(name+'-rejected',value in (0xfffffff0,0xffffffea))
        check(name+'-quarantined',word(LEASE)==3)
        check(name+'-source-held',call('a6400_descriptor_source_releasable',LEASE)==0)
        check(name+'-no-unsafe-free',len(events)==1)
        check(name+'-restore-blocked',call('a6400_descriptor_restore',LEASE,OPS)==0xfffffff0)
    reset();check('foreign-setup-install',call('a6400_descriptor_install',LEASE,GC,ARG,OPS)==0)
    put(GC+0x6c,0x209000);before=len(events)
    check('foreign-root-not-freed',call('a6400_descriptor_restore',LEASE,OPS)==0xffffff8c and len(events)==before)
    check('foreign-root-preserved',word(GC+0x6c)==0x209000)
    check('foreign-root-source-held',call('a6400_descriptor_source_releasable',LEASE)==0)
    put(GC+0x6c,clone);put(OPS+4,0x600200)
    check('changed-free-operation-rejected',call('a6400_descriptor_restore',LEASE,OPS)==0xffffffea and len(events)==before)
    reset('free-left-root');check('free-contract-install',call('a6400_descriptor_install',LEASE,GC,ARG,OPS)==0)
    check('free-contract-failure',call('a6400_descriptor_restore',LEASE,OPS)==0xfffffffb)
    check('free-contract-quarantine',word(LEASE)==3 and call('a6400_descriptor_source_releasable',LEASE)==0)
    before=len(events);check('free-not-retried',call('a6400_descriptor_restore',LEASE,OPS)==0xfffffff0 and len(events)==before)
    reset();cpu.mem_write(ARG+10,b'\x02')
    check('invalid-speed-before-save',call('a6400_descriptor_install',LEASE,GC,ARG,OPS)==0xffffffea and not events)
    # Execute real native save entry with no simulated allocator/copy return.
    # Stop BEFORE __copy_from_user, after lease has hidden the preserved root.
    reset();put(OPS,0x602bc550);put(OPS+4,0x602bc3e4)
    put(0x40e008,0xffffffff);native_run[0]=True
    call('a6400_descriptor_install',LEASE,GC,ARG,OPS)
    check('real-save-pre-service-stop',native_stopped[0])
    check('real-save-original-root-protected',word(GC+0x6c)==0 and word(LEASE+8)==OLD)
    check('real-save-native-argument-pointer',cpu.reg_read(UC_ARM_REG_R1)==ARG)
    check('real-save-no-recorder-ack',not events and word(LEASE)==1)
    if args.session:
        SESSION,REFERENCE,VECTOR,SESSION_OPS=0x202000,0x201000,0x201100,0x200e00
        def session_reset(name='success'):
            reset(name);op_counts.clear()
            for symbol in ('owner','current'):put(symbols[symbol],0)
            cpu.mem_write(SESSION,bytes(1024))
            # Independent original PC Remote graph, preserving the captured
            # HS interface/endpoint contract. This is an explicit fixture.
            cpu.mem_write(OLD,bytes(0x1000))
            old=bytearray(template[:88]);old[2:5]=bytes(3);old[18:21]=bytes(3)
            struct.pack_into('<I',old,8,OLD+0x100);struct.pack_into('<I',old,24,OLD+0x900)
            struct.pack_into('<I',old,60,OLD+0x500);cpu.mem_write(OLD,bytes(old))
            for index,base,group,alt,eps in [(0,0x100,0x200,0x300,0x400),(1,0x900,0xa00,0xb00,0xc00)]:
                source_cfg=word(TEMPLATE+index*16+8)
                config=bytearray(cpu.mem_read(source_cfg,24));config[2]=1
                source_group=word(source_cfg+4);source_alt=word(source_group+4)
                alternate=bytearray(cpu.mem_read(source_alt,20));source_eps=word(source_alt+4)
                struct.pack_into('<I',config,4,OLD+group);cpu.mem_write(OLD+base,bytes(config))
                cpu.mem_write(OLD+group,struct.pack('<BBBBI',0,1,0,0,OLD+alt))
                struct.pack_into('<I',alternate,4,OLD+eps);cpu.mem_write(OLD+alt,bytes(alternate))
                cpu.mem_write(OLD+eps,bytes(cpu.mem_read(source_eps,60)))
            language_ptr=word(TEMPLATE+60);entries=word(language_ptr+4)
            language=bytearray(cpu.mem_read(language_ptr,8));struct.pack_into('<I',language,4,OLD+0x600)
            cpu.mem_write(OLD+0x500,bytes(language))
            strings=bytearray(cpu.mem_read(entries,24))
            for i in range(3):
                ptr=struct.unpack_from('<I',strings,i*8+4)[0];size=strings[i*8+1]
                cpu.mem_write(OLD+0x700+i*0x50,bytes(cpu.mem_read(ptr,size)))
                struct.pack_into('<I',strings,i*8+4,OLD+0x700+i*0x50)
            cpu.mem_write(OLD+0x600,bytes(strings))
            ref=bytearray(60);struct.pack_into('<I',ref,0,0x201200);ref[4:6]=bytes([1,1])
            struct.pack_into('<I',ref,8,VECTOR);ref[12]=2
            for i in range(9):struct.pack_into('<I',ref,24+i*4,0x600900)
            cpu.mem_write(REFERENCE,bytes(ref));cpu.mem_write(VECTOR,b'\x01\x02');cpu.mem_write(0x201200,b'uvc-reference\0')
            cpu.mem_write(SESSION_OPS,struct.pack('<IIIIIIIII',0x600300,0x600400,0x600500,0x600600,0x600700,0x600800,0x600000,0x600100,0))
        def begin():return call('a6400_uvc_ptp_session_begin',SESSION,GC,REFERENCE,ARG,SESSION_OPS)
        def end():return call('a6400_uvc_ptp_session_end',SESSION)
        def releasable():return call('a6400_uvc_ptp_session_releasable',SESSION)
        session_reset();old_snapshot=bytes(cpu.mem_read(OLD,0x1000))
        check('session-begin',begin()==0)
        check('session-active',word(SESSION)==2 and releasable()==0)
        check('session-operation-order',[e['kind'] for e in events]==['quiesce','reg','reg','save_recorder','bind','resume'])
        check('session-only-uvc-registered',[e['wire'] for e in events if e['kind']=='reg']==[1,2])
        descriptor_run[0]=True
        cpu.mem_write(0x212000,struct.pack('<BBHHH',0x80,6,0x0200,0,173))
        expected=(args.input_dir/'unified-3-config.bin').read_bytes()
        size=call('a6400_uvc_ptp_candidate_descriptor_reply',TEMPLATE,GC,0x212000,0x218000,1024)
        check('session-active-native-ep0-path',size==173 and bytes(cpu.mem_read(0x218000,173))==expected)
        descriptor_run[0]=False
        bridge=call('probe_bridge',SESSION)
        for index,wire in [(0,1),(1,2)]:
            shadow=call('a6400_uvc_bridge_shadow',bridge,index)
            cpu.mem_write(0x212000,bytes([0xa1,0x81,0,1,wire,2,26,0]))
            function=word(shadow+0x2c)
            # Direct thunk call into the active bridge; terminal reference
            # callback is still an explicit recorder, not firmware behavior.
            symbols['probe_class_call']=function
            check('session-active-class-route-'+str(wire),call('probe_class_call',shadow,0x212000,0x213000)==0 and events[-1].get('arguments',[])[:3]==[REFERENCE,0x212000,0x213000])
        # Actual session endpoint selector and bridge START, with explicit
        # controller/endpoint fixtures. No UVC transfer is submitted.
        put(0x210fa4,0x215000);put(0x21501c,0x215100);put(0x21504c,1)
        cpu.mem_write(0x215100,bytes([7,5,0x84,2,0,2,0]))
        put(0x215224,0x215000);put(0x215600,0x215200)
        shadow=call('a6400_uvc_bridge_shadow',bridge,1)
        symbols['probe_start_call']=word(shadow+0x10)
        call('probe_start_call',shadow,3,0x68ab0001,0x215600)
        check('session-endpoint84-start-wrapper',events[-1].get('endpoint_wrapper')==0x215200)
        # Explicit test-driver STOP, not an inferred native hardware drain.
        check('session-fixture-stop',call('probe_stop',SESSION)==0)
        cleanup_start=len(events)
        check('session-end',end()==0 and releasable()==1)
        check('session-cleanup-order',[e['kind'] for e in events][cleanup_start:]==['quiesce','unbind','unreg','unreg','free_recorder','resume'])
        check('session-only-uvc-unregistered',[e['wire'] for e in events if e['kind']=='unreg']==[2,1])
        check('session-pc-remote-root-restored',word(GC+0x6c)==OLD and bytes(cpu.mem_read(OLD,0x1000))==old_snapshot)
        check('session-snapshot-restored',word(GC+0x68)==0x80000004 and bytes(cpu.mem_read(GC+0x84,2))==b'\1\1')
        before=len(events);check('session-repeat-end',end()==0 and len(events)==before)
        check('session-second-cycle',begin()==0 and end()==0 and releasable()==1)
        for name in ('reg-2','native-failure','bind','resume-shared'):
            session_reset(name);value=begin()
            check('session-failure-'+name,value!=0)
            check('session-rollback-'+name,releasable()==1 and word(GC+0x6c)==OLD)
            check('session-no-ptp-unregister-'+name,all(e['wire'] in (1,2) for e in events if e['kind']=='unreg'))
            check('session-no-old-free-'+name,all(e.get('root_before')!=OLD for e in events if e['kind']=='free_recorder'))
        for name in ('quiesce','unbind','resume-old'):
            session_reset(name)
            if name=='quiesce':value=begin()
            else:check('session-held-setup-'+name,begin()==0);value=end()
            check('session-held-error-'+name,value!=0 and word(SESSION)==3 and releasable()==0)
            scenario[0]='success'
            check('session-held-retry-'+name,end()==0 and releasable()==1 and word(GC+0x6c)==OLD)
        session_reset();check('session-inflight-setup',begin()==0)
        call('probe_inflight',SESSION,1);before=len(events)
        check('session-inflight-blocks-cleanup',end()==0xfffffff0 and releasable()==0 and [e['kind'] for e in events[before:]]==['quiesce'])
        call('probe_inflight',SESSION,0)
        check('session-after-fixture-drain',end()==0 and releasable()==1)
        session_reset('failure-left-root');check('session-copy-quarantine',begin()==0xfffffff0 and releasable()==0 and word(SESSION)==3)
        check('session-copy-quarantine-no-free',not any(e['kind']=='free_recorder' for e in events))
        session_reset();cpu.mem_write(OLD+50,b'\x22')
        check('session-reject-non-pc-remote-before-hardware',begin()==0xffffffea and not events)
        session_reset();cpu.mem_write(VECTOR,b'\0\1')
        check('session-reject-legacy-interfaces-before-hardware',begin()==0xffffffea and not events)
    if args.native_backend:
        BACKEND,NATIVE_OPS=0x203000,0x204000
        originals=[word(a) for a in sites]
        cpu.mem_protect(0x602b9000,4096,7) # Explicit writable hook-page fixture only
        def backend_reset():
            backend_run[0]=False;native_fault[0]='';descriptor_run[0]=False;extra_stop[0]=None
            session_reset();put(symbols['live'],0)
            cpu.mem_write(BACKEND,bytes(256));cpu.mem_write(NATIVE_OPS,bytes(128))
            put(0x6051b17c,GC);put(GC+8,0x214000);put(0x214000,0x218000)
            put(0x211010,0x217000);put(0x217014,0x602b1d3c)
            put(0x210f80,0x215800);put(0x210f84,0x215900)
            put(0x215848,0x210eb0);put(0x215948,0x210eb0)
            for a,v in zip(sites,originals):put(a,v)
            gcw[0]=2;registry.clear();registry.add(0x207000);events.clear()
            registry_next[0]=0x206000
            put(0x207100,0x207000);put(0x207104,GC+0x78);put(0x207108,GC+0x78)
            cpu.mem_write(0x207114,b'\x01');put(GC+0x78,0x207104);put(GC+0x7c,0x207104)
            put(0x40e008,0xbfffffff);backend_run[0]=True
        def backend_init():return call('a6400_uvc_ptp_native_backend_init',BACKEND,SESSION,TEMPLATE,NATIVE_OPS)
        def native_begin():return call('a6400_uvc_ptp_session_begin',SESSION,GC,REFERENCE,ARG,NATIVE_OPS)
        backend_reset();check('native-backend-init-fingerprints',backend_init()==0)
        check('native-backend-session-begin',native_begin()==0)
        check('native-backend-branches-installed',all(word(a)!=v for a,v in zip(sites,originals)))
        check('native-backend-address-limit-restored',word(0x40e008)==0xbfffffff)
        saves=[e for e in events if e['kind']=='native-save']
        check('native-backend-save-limit-and-root',len(saves)==1 and saves[0]['address_limit']==0xffffffff and saves[0]['root_before']==0)
        check('native-backend-reg-flags-guard',all(e['flags']&4==0 for e in events if e['kind']=='native-reg'))
        check('native-backend-retire-while-active-blocked',call('a6400_uvc_ptp_native_backend_retire',BACKEND)==0xfffffff0)
        # Execute the actual patched BL, compiled backend dispatcher and real
        # original Sony serializers. Kernel/hardware operations above are doubles.
        cpu.mem_write(0x212000,struct.pack('<BBHHH',0x80,6,0x0200,0,173))
        symbols['probe_native_ep0']=0x602b95cc;extra_stop[0]=0x602b95d0;descriptor_run[0]=True
        size=call('probe_native_ep0',GC,0x212000,0x218000)
        check('native-backend-patched-bl-ep0-output',size==173 and bytes(cpu.mem_read(0x218000,173))==(args.input_dir/'unified-3-config.bin').read_bytes())
        descriptor_run[0]=False;extra_stop[0]=None
        check('native-backend-session-end',end()==0)
        check('native-backend-original-branches-restored',all(word(a)==v for a,v in zip(sites,originals)))
        check('native-backend-ptp-registration-preserved',registry=={0x207000})
        check('native-backend-only-copy-freed',[e['root_before'] for e in events if e['kind']=='native-free']==[clone])
        check('native-backend-source-releasable',releasable()==1 and word(GC+0x6c)==OLD)
        check('native-backend-retire',call('a6400_uvc_ptp_native_backend_retire',BACKEND)==0)
        backend_reset();put(sites[2],originals[2]^1)
        check('native-backend-reject-foreign-hook',backend_init()==0xffffff8c and not events)
        backend_reset()
        # A changed original instruction is a fixture write, restored before
        # any native call. Text stays read-only to the compiled backend.
        expected_word=word(0x602b8610);put(0x602b8610,expected_word^1)
        check('native-backend-reject-code-mismatch',backend_init()==0xffffff8c and not events)
        put(0x602b8610,expected_word)
        backend_reset();put(0x217014,0x600a00)
        check('native-backend-reject-foreign-pullup-before-owner',backend_init()==0xffffff8c and not events)
        check('native-backend-reject-target-keeps-source-idle',releasable()==1)
        backend_reset();put(0x211010,0)
        check('native-backend-reject-null-gadget-ops',backend_init()==0xffffffea and not events)
        backend_reset();check('native-backend-changed-pullup-setup',backend_init()==0 and native_begin()==0)
        installed=word(GC+0x6c);events.clear();put(0x217014,0x600a00)
        check('native-backend-changed-pullup-holds-before-call',end()==0xffffff8c and not events)
        check('native-backend-changed-pullup-preserves-owned-root',word(GC+0x6c)==installed and releasable()==0)
        put(0x217014,0x602b1d3c)
        check('native-backend-restored-target-allows-cleanup',end()==0 and releasable()==1)
        check('native-backend-restored-target-retire',call('a6400_uvc_ptp_native_backend_retire',BACKEND)==0)
        backend_reset();check('native-backend-conflict-setup',backend_init()==0)
        gcw[0]=1;put(sites[1],originals[1]^1);before=[word(a) for a in sites]
        symbols['probe_native_bind']=word(NATIVE_OPS+8)
        check('native-backend-bind-preflight-no-partial-write',call('probe_native_bind',GC,TEMPLATE)==0xffffff8c and [word(a) for a in sites]==before)
        backend_reset();check('native-backend-unregister-error-setup',backend_init()==0 and native_begin()==0)
        cpu.mem_write(GC+0x74,b'\0')
        # Changing the bound GC global makes native void unregister reject;
        # check_error exposes that rejection so the session may not retire.
        put(0x6051b17c,0)
        symbols['probe_native_unreg']=word(NATIVE_OPS+20)
        call('probe_native_unreg',0x207000)
        put(0x6051b17c,GC)
        check('native-backend-void-error-holds-session',end()!=0 and releasable()==0)
        backend_reset();check('native-backend-unreg-return-setup',backend_init()==0 and native_begin()==0)
        native_fault[0]='unreg-error'
        check('native-backend-unreg-return-holds-session',end()==0xfffffff0 and releasable()==0)
        check('native-backend-unreg-failure-no-descriptor-free',not any(e['kind']=='native-free' for e in events))
        backend_reset();check('native-backend-save-failure-setup',backend_init()==0)
        native_fault[0]='save-error'
        check('native-backend-save-failure-propagated',native_begin()==0xfffffff4 and releasable()==1)
        check('native-backend-save-failure-limit-restored',word(0x40e008)==0xbfffffff)
        check('native-backend-save-failure-pc-remote-restored',word(GC+0x6c)==OLD and registry=={0x207000})
    report=dict(status='offline_transaction_controls_passed',check_count=len(checks),checks=checks,
        camera_access=False,deployed=False,deployable=False,kernel_sha256=KERNEL_SHA,
        elf_sha256=hashlib.sha256(binary).hexdigest(),
        input_manifest_sha256=hashlib.sha256((args.input_dir/'manifest.json').read_bytes()).hexdigest(),
        files={rel(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [*sources,*[s.with_suffix('.h') for s in sources if s.with_suffix('.h').exists()],target]},
        limitations=['Controller quiescence, callback draining, serialization lock and native address-limit setup are CALLER PRECONDITIONS, not implemented here.',
            'Save/free success/failure are EXPLICIT RECORDERS for MOD transaction-state tests, not native allocator or hardware acknowledgements.',
            'Real original save_desc_tbl entry stops before copy/allocator services; it does not complete installation.',
            'No common UVC/PTP registration, USB enumeration, rollback on camera or sensor stream is proven.'])
    if args.session:
        report['limitations'].append('In the session-only subset, controller, EP0 hook, driver register/unregister and reference callbacks are EXPLICIT RECORDERS; that subset proves MOD ordering/state, not hardware acknowledgements.')
    if args.native_backend:
        report['limitations'][0]='Native wrappers implement address-limit save/restore and guarded kernel targets; live serialization and complete physical consumer quiescence remain unproven.'
        report['limitations'].append('Native wrapper operations target actual kernel addresses, but their kernel/hardware service effects are EXPLICIT DOUBLES. Patched BL -> compiled backend -> original descriptor serializers executes for real offline; no physical enumeration/stream claim.')
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
