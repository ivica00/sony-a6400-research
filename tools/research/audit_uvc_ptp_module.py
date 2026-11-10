"""Audit shared .ko structure and execute compiled ioctl/release guards offline.

Kernel copy services and original core ioctl/release entries are explicit
recorders. Does not load the module or execute its init/exit on a camera.
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
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC,UC_CPU_ARM_CORTEX_A9
from tools.research.build_uvc_composite_module import ROOT,REF_KO,REF_SHA


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--linked-elf',type=Path,help='Use a prebuilt fixture ELF; skip gcc/ld (WSL-less environments)')
    parser.add_argument('--prepare-only',action='store_true',help='Write the fixture and the exact gcc/ld commands, then exit')
    args=parser.parse_args();out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):parser.error('Output must be under artifacts')
    out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((args.build_dir/'manifest.json').read_text())
    if not manifest['shared_ptp_enumeration_candidate'] or not manifest['start_probe_only']:raise ValueError('Not an enumeration candidate')
    for relative,sha in manifest['files'].items():
        if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()!=sha:raise ValueError('Candidate input changed: '+relative)
    module=(args.build_dir/manifest['target']).resolve();raw=module.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=manifest['sha256']:raise ValueError('Module identity mismatch')
    original=REF_KO.read_bytes()
    if hashlib.sha256(original).hexdigest()!=REF_SHA:raise ValueError('Original reference identity mismatch')
    elf=ELFFile(io.BytesIO(raw));orig=ELFFile(io.BytesIO(original));sym=elf.get_section_by_name('.symtab')
    checks=[]
    def check(name,value):
        if not value:raise AssertionError(name)
        checks.append(name)
    rels={r['r_offset']:sym.get_symbol(r['r_info_sym']).name for r in elf.get_section_by_name('.rel.data').iter_relocations()}
    check('file-operations-owner-this-module',rels.get(0x44)=='__this_module')
    check('file-operations-ioctl-guard',rels.get(0x64)=='a6400_uvc_shared_ioctl')
    check('file-operations-release-guard',rels.get(0x78)=='a6400_uvc_shared_release')
    imports_set={s.name for s in sym.iter_symbols() if s.name and s['st_shndx']=='SHN_UNDEF'}
    check('self-pin-native-reference-contract',{'module_put','__per_cpu_offset','nr_cpu_ids','preempt_schedule'}<=imports_set and not {'__symbol_get','__symbol_put'}&imports_set)
    from tools.research.kernel_export_contract import kernel_exports
    exports=kernel_exports()
    check('no-gpl-only-kernel-imports',not any(exports[n]['kind']=='gpl' for n in imports_set if n in exports))
    text=elf.get_section_by_name('.text').data();old=orig.get_section_by_name('.text').data()
    changed=[i for i,(a,b) in enumerate(zip(old,text)) if a!=b]
    check('only-documented-reference-instructions-changed',changed==[0x116c,0x13e8,0x13ea])
    for name in ('.init.text','.exit.text'):
        check('original-'+name+'-preserved',elf.get_section_by_name(name).data().startswith(orig.get_section_by_name(name).data()))
    modinfo=elf.get_section_by_name('.modinfo').data()
    check('native-vermagic',b'vermagic=3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7 \0' in modinfo)
    fixture=out/'module_guard_fixture.c'
    fixture.write_text('#include "uvc_ptp_session.h"\nvoid probe_active(struct a6400_uvc_ptp_session *s){s->phase=A6400_SESSION_ACTIVE;}\nvoid probe_idle(struct a6400_uvc_ptp_session *s){unsigned int i;for(i=0;i<sizeof(*s);++i)((unsigned char*)s)[i]=0;}\nvoid probe_hold(struct a6400_uvc_ptp_session *s,void *gc,void(*free_op)(void*)){s->phase=A6400_SESSION_HELD;s->stopped=1;s->gc=gc;s->lease.phase=A6400_LEASE_QUARANTINED;s->ops.descriptor.free=free_op;}\n',encoding='utf-8')
    with fixture.open('a',encoding='utf-8') as f:
        f.write('#include "uvc_ptp_stop_attest.h"\nint probe_consume(void *ctx,const struct a6400_verified_stops *s){unsigned int *out=ctx;out[0]=s->owner;out[1]=s->count;out[2]=s->tids[0];out[3]=s->tids[s->count-1];return -7;}\n')
        f.write('#include "uvc_ptp_native_backend.h"\nvoid probe_backend_gc(struct a6400_uvc_ptp_native_backend *b,void *gc){b->gc=gc;}\n')
    def run(command):
        if os.name=='nt':command=['wsl.exe','--cd','/mnt/'+ROOT.drive[0].lower()+ROOT.as_posix()[2:],'--exec',*command]
        subprocess.run(command,cwd=ROOT,check=True)
    rel=lambda p:p.relative_to(ROOT).as_posix()
    obj=out/'module_guard_fixture.o';linked=out/'module-guards.elf'
    imports=sorted(s.name for s in sym.iter_symbols() if s.name and s['st_shndx']=='SHN_UNDEF')
    addresses={name:0x700000+i*256 for i,name in enumerate(imports)}
    gcc=['arm-linux-gnueabi-gcc','-marm','-march=armv7-a','-mfloat-abi=softfp','-ffreestanding','-fno-builtin','-fno-pic','-fno-pie','-O2','-Itools/native_camera','-c',rel(fixture),'-o',rel(obj)]
    ld=['arm-linux-gnueabi-ld','--no-undefined','-Ttext=0x5f800000','-Tdata=0x5f810000','-z','max-page-size=4096',
        '-e','0x5f800000','-o',rel(linked),rel(module),rel(obj),
        *['--defsym='+name+'='+hex(address) for name,address in addresses.items()]]
    if args.prepare_only:
        (out/'prepare.json').write_text(json.dumps({'gcc':gcc,'ld':ld,'fixture':rel(fixture),'obj':rel(obj),'linked':rel(linked)},indent=2)+'\n')
        print(json.dumps({'prepare':str(out/'prepare.json')}))
        return
    if args.linked_elf:
        linked=args.linked_elf.resolve()
    else:
        run(gcc);run(ld)
    image=ELFFile(io.BytesIO(linked.read_bytes()));symbols={s.name:s['st_value'] for s in image.get_section_by_name('.symtab').iter_symbols() if s['st_shndx']!='SHN_UNDEF'}
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A9);pages=set();writable=[];executable=[]
    for segment in image.iter_segments():
        if segment['p_type']!='PT_LOAD':continue
        for page in range(segment['p_vaddr']&~4095,(segment['p_vaddr']+segment['p_memsz']+4095)&~4095,4096):
            if page not in pages:cpu.mem_map(page,4096);pages.add(page)
        cpu.mem_write(segment['p_vaddr'],segment.data())
        if segment['p_flags']&2:writable.append((segment['p_vaddr'],segment['p_vaddr']+segment['p_memsz']))
        if segment['p_flags']&1:executable.append((segment['p_vaddr'],segment['p_vaddr']+segment['p_memsz']))
    cpu.mem_map(0x200000,0x20000);cpu.mem_map(0x400000,0x10000);cpu.mem_map(0x500000,4096)
    cpu.mem_map(0x700000,0x10000);cpu.mem_map(0x602b8000,4096);cpu.mem_map(0x604e5000,4096)
    cpu.mem_map(0x6013f000,4096)
    cpu.mem_map(0x60119000,4096)
    cpu.mem_map(0x6051b000,4096)
    cpu.mem_write(0x60119de4,struct.pack('<II',0xee103f30,0xe1a03823))
    cpu.mem_write(0x6013f324,struct.pack('<II',0xe1a0c00d,0xe92dd9f0))
    executable.append((0x602b8000,0x602b9000))
    cpu.mem_write(0x602b8844,bytes.fromhex('1eff2fe1'))
    for address in addresses.values():cpu.mem_write(address,bytes.fromhex('1eff2fe1'))
    cpu.mem_write(addresses['cpu_cache']+16,struct.pack('<I',0x60119de4))
    cpu.mem_write(addresses['cpu_online_mask'],struct.pack('<I',0x20b000))
    cpu.mem_write(0x20b000,struct.pack('<I',15))
    cpu.mem_write(addresses['nr_cpu_ids'],struct.pack('<I',4))
    events=[];core_fault=[0];attest_calls=[]
    entry_native_calls=[]
    self_ref=dict(count=0,error=0,gets=0,puts=0)
    cache_state=dict(seen=15,coherent_calls=0,ipi_calls=0)
    attest_state=dict(error_tid=0,badmode=False,badsignal=False,membership='ok',opened=False,tid=0,mutate_input=False)
    def hook(machine,pc,size,user):
        if pc==0x500000:machine.emu_stop();return
        if pc==symbols['a6400_uvc_native_ioctl_tail']:
            entry_native_calls.append(machine.reg_read(UC_ARM_REG_R1))
            assert struct.unpack('<I',machine.mem_read(symbols['entry_guard'],4))[0]==1
            machine.reg_write(UC_ARM_REG_R0,0xffffffe7);machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
        if pc==0x60119de4:
            assert self_ref['count']==1
            r0=machine.reg_read(UC_ARM_REG_R0);r1=machine.reg_read(UC_ARM_REG_R1)
            assert (r0==symbols['test_slot'] and r1==symbols['test_slot']+4) or (r0==0x602b8844 and r1==0x602b8848)
            cache_state['coherent_calls']+=1
            machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
        if pc in (symbols['a6400_module_self_get'],symbols['a6400_module_self_put']):
            if pc==symbols['a6400_module_self_get']:
                assert self_ref['count']==0;self_ref['gets']+=1
                result=self_ref['error']
                if not result:self_ref['count']=1
            else:
                assert self_ref['count']==1;self_ref['puts']+=1;self_ref['count']=0;result=0
            machine.reg_write(UC_ARM_REG_R0,result&0xffffffff)
            machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
        if pc==0x6013f324:
            request=machine.reg_read(UC_ARM_REG_R0);tid=machine.reg_read(UC_ARM_REG_R1)
            output=machine.reg_read(UC_ARM_REG_R3);attest_calls.append((request,tid))
            assert 0x400000<=output<0x410000
            assert struct.unpack('<I',machine.mem_read(0x40e008,4))[0]==0xffffffff
            result=-3 if tid==attest_state['error_tid'] else 0
            if not result:
                if request==12:
                    words=[0]*18;words[16]=19 if attest_state['badmode'] else 16
                    machine.mem_write(output,struct.pack('<18I',*words))
                else:
                    assert request==0x4202
                    machine.mem_write(output,struct.pack('<III',5 if attest_state['badsignal'] else 19,0,0)+bytes(116))
            machine.reg_write(UC_ARM_REG_R0,result&0xffffffff)
            machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
        if pc==0x602b8844:
            events.append('native-gadgetcore-ioctl')
            machine.reg_write(UC_ARM_REG_R0,0);machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
        if pc in (symbols['usbg_video_core_ioctl'],symbols['usbg_video_core_release']):
            events.append('original-ioctl' if pc==symbols['usbg_video_core_ioctl'] else 'original-release')
            if core_fault[0]:
                machine.mem_write(symbols['native_guard']+8,struct.pack('<I',core_fault[0]));core_fault[0]=0
            machine.reg_write(UC_ARM_REG_R0,0);machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
        if pc in addresses.values():
            name=next(name for name,address in addresses.items() if address==pc)
            if name=='on_each_cpu':
                assert self_ref['count']==1 and machine.reg_read(UC_ARM_REG_R2)==1
                assert machine.reg_read(UC_ARM_REG_R0)==symbols['synchronize_cpu']
                assert cache_state['coherent_calls']==cache_state['ipi_calls']+1
                cache_state['ipi_calls']+=1
                machine.mem_write(machine.reg_read(UC_ARM_REG_R1),struct.pack('<II',cache_state['seen'],0))
                machine.reg_write(UC_ARM_REG_R0,0);machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
            if name=='printk':
                machine.reg_write(UC_ARM_REG_R0,0);machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
            if name=='memset':
                destination=machine.reg_read(UC_ARM_REG_R0);value=machine.reg_read(UC_ARM_REG_R1);length=machine.reg_read(UC_ARM_REG_R2)
                assert 0x400000<=destination and destination+length<=0x410000
                machine.mem_write(destination,bytes([value&255])*length)
                machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
            if name in ('filp_open','vfs_read','filp_close'):
                result=0
                if name=='filp_open':
                    path=bytes(machine.mem_read(machine.reg_read(UC_ARM_REG_R0),64)).split(b'\0')[0].decode()
                    import re
                    match=re.fullmatch(r'/proc/149/task/(\d+)/status',path)
                    assert match and not attest_state['opened']
                    attest_state['tid']=int(match[1])
                    if attest_state['mutate_input']:
                        machine.mem_write(0x206000,struct.pack('<II',703,704))
                    if attest_state['membership']=='open-error':result=-2
                    else:attest_state['opened']=True;result=0x20a000
                elif name=='filp_close':
                    assert attest_state['opened'] and machine.reg_read(UC_ARM_REG_R0)==0x20a000
                    assert struct.unpack('<I',machine.mem_read(0x40e008,4))[0]==0x60000000
                    attest_state['opened']=False
                    result=-5 if attest_state['membership']=='close-error' else 0
                else:
                    assert attest_state['opened'] and machine.reg_read(UC_ARM_REG_R0)==0x20a000
                    assert struct.unpack('<I',machine.mem_read(0x40e008,4))[0]==0xffffffff
                    tid=attest_state['tid'];mode=attest_state['membership']
                    thread_count=struct.unpack('<I',machine.mem_read(0x205008,4))[0]
                    text=f'Name:\tim.elf\nTgid:\t{703 if mode=="wrong-tgid" else 149}\nPid:\t{703 if mode=="wrong-pid" else tid}\nTracerPid:\t999\nThreads:\t{thread_count+1 if mode=="wrong-count" else thread_count}\n'
                    if mode=='duplicate':text+='Tgid:\t149\n'
                    if mode=='short':text='Name:\tim.elf\n'
                    if mode=='read-error':result=-5
                    else:
                        raw_status=text.encode();machine.mem_write(machine.reg_read(UC_ARM_REG_R1),raw_status);result=len(raw_status)
                machine.reg_write(UC_ARM_REG_R0,result&0xffffffff)
                machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
            if name in ('__copy_to_user','__copy_from_user'):
                dst=machine.reg_read(UC_ARM_REG_R0);src=machine.reg_read(UC_ARM_REG_R1);n=machine.reg_read(UC_ARM_REG_R2)
                machine.mem_write(dst,bytes(machine.mem_read(src,n)));machine.reg_write(UC_ARM_REG_R0,0)
            elif name=='printk':machine.reg_write(UC_ARM_REG_R0,0)
            else:raise RuntimeError('Unexpected imported service '+name)
            machine.reg_write(UC_ARM_REG_PC,machine.reg_read(UC_ARM_REG_LR));return
        if not any(a<=pc and pc+size<=b for a,b in executable):raise RuntimeError(f'Unexpected execution {pc:08x}')
    def guard(machine,access,address,size,value,user):
        if any(a<=address and address+size<=b for a,b in [*writable,(0x200000,0x220000),(0x400000,0x410000),(0x602b8844,0x602b8848)]):return
        raise RuntimeError(f'Unexpected write {address:08x}')
    cpu.hook_add(UC_HOOK_CODE,hook);cpu.hook_add(UC_HOOK_MEM_WRITE,guard)
    def put(address,value):cpu.mem_write(address,struct.pack('<I',value))
    def call(name,*values):
        for register,value in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),values):cpu.reg_write(register,value)
        cpu.reg_write(UC_ARM_REG_SP,0x40f000);cpu.reg_write(UC_ARM_REG_LR,0x500000)
        try:cpu.emu_start(symbols[name],0xffffffff,count=100000)
        except Exception as error:
            raise RuntimeError(f'{name}: PC={cpu.reg_read(UC_ARM_REG_PC):08x} LR={cpu.reg_read(UC_ARM_REG_LR):08x} SP={cpu.reg_read(UC_ARM_REG_SP):08x}') from error
        if cpu.reg_read(UC_ARM_REG_PC)!=0x500000:raise RuntimeError('Missing bounded return')
        return cpu.reg_read(UC_ARM_REG_R0)
    data=image.get_section_by_name('.data')['sh_addr']
    word=lambda address:struct.unpack('<I',cpu.mem_read(address,4))[0]
    check('linked-file-owner',word(data+0x44)==symbols['__this_module'])
    check('linked-ioctl-target',word(data+0x64)==symbols['a6400_uvc_shared_ioctl'])
    check('linked-release-target',word(data+0x78)==symbols['a6400_uvc_shared_release'])
    for cmd in (0x4008f003,0xf006,0xf002,0x4008f000,0xf001,0x12345678):
        before=len(events)
        check('enum-reject-'+hex(cmd),call('a6400_uvc_shared_ioctl',0,cmd,0)==0xffffffa1 and len(events)==before)
    check('status-default',call('a6400_uvc_shared_ioctl',0,0x8010f022,0x205000)==0 and bytes(cpu.mem_read(0x205000,16))==bytes(16))
    check('status-null-output',call('a6400_uvc_shared_ioctl',0,0x8010f022,0)==0xfffffff2)
    check('runtime-rejects-idle-backend',call('a6400_uvc_shared_ioctl',0,0x8010f029,0x205000)==0xffffffed)
    call('probe_backend_gc',symbols['backend'],0x210000);put(symbols['live'],symbols['backend'])
    put(0x6051b17c,0x210000);put(0x210000,0x210800);put(0x210068,4)
    cpu.mem_write(0x210074,bytes([1]));cpu.mem_write(0x210084,bytes([1,3]))
    check('runtime-reads-native-configuration',call('a6400_uvc_shared_ioctl',0,0x8010f029,0x205000)==0 and struct.unpack('<4I',cpu.mem_read(0x205000,16))==(4,1,1,3))
    check('runtime-null-output',call('a6400_uvc_shared_ioctl',0,0x8010f029,0)==0xfffffff2)
    put(0x6051b17c,0x210400)
    check('runtime-rejects-changed-gc',call('a6400_uvc_shared_ioctl',0,0x8010f029,0x205000)==0xffffffed)
    call('probe_backend_gc',symbols['backend'],0);put(symbols['live'],0);put(0x6051b17c,0)
    call('a6400_uvc_shared_ioctl',0,0x8010f022,0x205000)
    check('traced-native-wrapper-preserves-result',call('a6400_uvc_native_entry_wrapper',0,0x12345678,0)==0xffffffe7 and entry_native_calls[-1]==0x12345678)
    put(symbols['entry_guard'],0x80000000);entry_count=len(entry_native_calls)
    check('traced-native-wrapper-held-does-not-forward',call('a6400_uvc_native_entry_wrapper',0,0xe202,0)==0xfffffff0 and len(entry_native_calls)==entry_count)
    put(symbols['entry_guard'],0)
    def attest(tids=(149,150),version=2,owner=149,count=None,reserved=0):
        put(0x40e008,0x60000000)
        cpu.mem_write(0x206000,struct.pack('<'+'I'*len(tids),*tids))
        cpu.mem_write(0x205000,struct.pack('<8I',version,owner,len(tids) if count is None else count,0x206000,reserved,0,999,999))
        return call('a6400_uvc_shared_ioctl',0,0xc020f023,0x205000)
    check('attest-null-request',call('a6400_uvc_shared_ioctl',0,0xc020f023,0)==0xfffffff2)
    check('attest-valid-two-traced-recorders',attest()==0 and word(0x205018)==2 and len(attest_calls)==4)
    check('attest-native-snapshot-restores-address-limit',word(0x40e008)==0x60000000)
    attest_state['mutate_input']=True
    check('attest-copied-tids-survive-user-input-mutation',attest()==0 and attest_calls[-4:]==[(12,149),(0x4202,149),(12,150),(0x4202,150)] and word(0x206000)==703)
    attest_state['mutate_input']=False
    check('attest-idle-reservation-released',word(symbols['native_guard'])==0 and word(symbols['native_reserved'])==0)
    for name,kwargs in [('legacy-version',dict(version=1)),('user-scratch',dict(reserved=0x207000)),('scope',dict(owner=703)),('zero-count',dict(count=0)),('large-count',dict(count=513)),('duplicate',dict(tids=(149,149))),('zero-tid',dict(tids=(0,))),('missing-leader',dict(tids=(150,)))]:
        before=len(attest_calls)
        check('attest-reject-'+name,attest(**kwargs)==0xffffffea and word(0x205018)==0 and len(attest_calls)==before)
    attest_state['error_tid']=150
    check('attest-partial-error-count',attest()==0xfffffffd and word(0x205018)==1 and word(0x20501c)==0xfffffffd and word(0x40e008)==0x60000000)
    attest_state['error_tid']=0;attest_state['badmode']=True
    check('attest-rejects-nonuser-registers',attest()==0xffffff8c and word(0x205018)==0)
    attest_state['badmode']=False;attest_state['badsignal']=True
    check('attest-rejects-other-stop-signal',attest()==0xffffff8c and word(0x205018)==0)
    attest_state['badsignal']=False
    put(0x6013f324,0)
    check('attest-rejects-native-fingerprint-change',attest()==0xffffff8c)
    put(0x6013f324,0xe1a0c00d)
    for mode,error in [('open-error',-2),('read-error',-5),('close-error',-5),('wrong-tgid',-116),('wrong-pid',-116),('wrong-count',-116),('duplicate',-116),('short',-116)]:
        before=len(attest_calls);attest_state['membership']=mode
        check('attest-member-'+mode,attest()==(error&0xffffffff) and word(0x205018)==0 and len(attest_calls)==before)
        check('attest-member-cleanup-'+mode,not attest_state['opened'] and word(0x40e008)==0x60000000)
    attest_state['membership']='ok'
    put(0x604e5098,0x602b8844)
    before_route=word(0x604e5098)
    def shadow():return call('a6400_uvc_shared_ioctl',0,0xc020f024,0x205000)
    attest()
    check('shadow-route-full-cycle',shadow()==0 and self_ref['count']==0 and word(symbols['test_slot'])==0x13572468)
    check('shadow-route-native-slot-unchanged',word(0x604e5098)==before_route)
    check('shadow-route-repeat-cycle',shadow()==0 and self_ref['gets']==2 and self_ref['puts']==2)
    self_ref['error']=-12
    check('shadow-route-pin-failure',shadow()==0xfffffff4 and self_ref['count']==0 and word(symbols['test_slot'])==0x13572468)
    self_ref['error']=0
    put(symbols['test_slot'],0xdeadbeef)
    check('shadow-route-foreign-word-held',shadow()==0xffffff8c and self_ref['count']==1 and word(symbols['lease'])==2 and word(symbols['test_slot'])==0xdeadbeef)
    check('shadow-route-recovery-keeps-foreign-word',shadow()==0xffffff8c and self_ref['count']==1 and word(symbols['test_slot'])==0xdeadbeef)
    put(symbols['test_slot'],0x13572468)
    check('shadow-route-held-recovery',shadow()==0 and self_ref['count']==0 and word(symbols['lease'])==0)
    cache_state['seen']=1
    check('shadow-route-missing-core-retains-pin',shadow()==0xfffffff0 and self_ref['count']==1 and word(symbols['lease'])==2)
    cache_state['seen']=15
    check('shadow-route-cache-recovery',shadow()==0 and self_ref['count']==0 and word(symbols['lease'])==0)
    attest_state['membership']='wrong-tgid';gets=self_ref['gets']
    check('shadow-route-invalid-scope-skips-pin',shadow()==0xffffff8c and self_ref['gets']==gets)
    attest_state['membership']='ok'
    cpu.mem_write(0x20c000,bytes(8))
    for cpu_number in range(4):
        put(0x40e014,cpu_number);call('synchronize_cpu',0x20c000)
    check('compiled-per-core-sync-callback-mask',word(0x20c000)==15 and word(0x20c004)==0)
    put(0x40e014,32);call('synchronize_cpu',0x20c000)
    check('compiled-per-core-sync-rejects-out-of-range',word(0x20c004)==0xffffffea)
    put(0x40e014,0)
    attest()
    cpu.mem_write(0x209000,bytes(16))
    check('attest-synchronous-kernel-scope-consumer',call('a6400_uvc_with_stops',0x205000,symbols['probe_consume'],0x209000)==0xfffffff9 and struct.unpack('<4I',cpu.mem_read(0x209000,16))==(149,2,149,150))
    check('attest-consumer-error-receipt',word(0x205018)==2 and word(0x20501c)==0xfffffff9)
    attest_state['membership']='wrong-tgid'
    cpu.mem_write(0x209000,bytes(16))
    check('attest-invalid-scope-skips-consumer',call('a6400_uvc_with_stops',0x205000,symbols['probe_consume'],0x209000)==0xffffff8c and bytes(cpu.mem_read(0x209000,16))==bytes(16))
    attest_state['membership']='ok'
    check('idle-stop-forwarded',call('a6400_uvc_shared_ioctl',0,0xe001,0)==0 and events[-1]=='original-ioctl')
    check('clean-release-forwarded',call('a6400_uvc_shared_release',0,0)==0 and events[-1]=='original-release')
    guard_sym=symbols['native_guard']
    put(guard_sym,1);before=len(events)
    check('concurrent-release-rejected',call('a6400_uvc_shared_release',0,0)==0xfffffff0 and len(events)==before)
    check('concurrent-ioctl-rejected',call('a6400_uvc_shared_ioctl',0,0xe001,0)==0xfffffff0 and len(events)==before)
    put(guard_sym,0);put(0x604e5098,0x602b8844);before=len(events)
    check('activation-rejects-unpublished-wrapper',call('a6400_uvc_shared_ioctl',0,0x4038e000,0)==0xffffffed and len(events)==before)
    check('unpublished-rejection-releases-idle-reservation',word(guard_sym)==0 and word(symbols['native_reserved'])==0)
    put(0x604e5098,symbols['a6400_uvc_native_gadgetcore_ioctl'])
    check('bound-route-allows-core-entry-recorder',call('a6400_uvc_shared_ioctl',0,0x4038e000,0)==0 and events[-1]=='original-ioctl')
    core_fault[0]=0xfffffffb
    check('reservation-release-failure-propagated',call('a6400_uvc_shared_ioctl',0,0x4038e000,0)==0xfffffffb)
    check('reservation-release-failure-keeps-ownership',word(guard_sym)==0x80000000 and word(symbols['native_reserved'])==1)
    before=len(events)
    check('guard-fault-cause-not-replaced-with-busy',call('a6400_uvc_shared_ioctl',0,0xe001,0)==0xfffffffb and len(events)==before)
    put(guard_sym+8,0) # Explicit test fault removal, not a camera recovery claim.
    check('test-fault-cleared-idle-reservation-released',call('a6400_uvc_shared_ioctl',0,0x8010f022,0x205000)==0 and word(guard_sym)==0 and word(symbols['native_reserved'])==0)
    for n in (0xffffffff,140000):
        cpu.mem_write(0x205000,struct.pack('<II',n,0));before=len(events)
        check('legacy-dma-overflow-reject-'+str(n),call('a6400_uvc_legacy_dma_ioctl',0,0x4008f003,0x205000)==0xffffffea and len(events)==before)
    cpu.mem_write(0x205000,struct.pack('<II',131060,0x14000000));before=len(events)
    check('legacy-dma-boundary-forwarded',call('a6400_uvc_legacy_dma_ioctl',0,0x4008f003,0x205000)==0 and len(events)==before+1)
    put(symbols['g_dma_phys'],0x05280000)
    for label,size,address in [('zero-size',0,0x14000000),('null-source',128,0),('wrapped-source',128,0xfffffff0),
                               ('owned-slot-zero',128,0x05280000),('owned-slot-one',128,0x052a0000),
                               ('overlap-from-before',128,0x0527ffc0)]:
        cpu.mem_write(0x205000,struct.pack('<II',size,address));before=len(events)
        check('legacy-dma-source-reject-'+label,call('a6400_uvc_legacy_dma_ioctl',0,0x4008f003,0x205000)==0xffffffea and len(events)==before)
    cpu.mem_write(0x205000,struct.pack('<II',128,0x052c0000));before=len(events)
    check('legacy-dma-disjoint-source-after-owned-pool',call('a6400_uvc_legacy_dma_ioctl',0,0x4008f003,0x205000)==0 and len(events)==before+1)
    put(symbols['g_dma_phys'],0)
    put(symbols['pinned'],1);put(symbols['owner'],symbols['session'])
    call('probe_active',symbols['session'])
    check('active-shadow-route-rejected',shadow()==0xfffffff0)
    before=len(attest_calls)
    check('active-attestation-rejected',attest()==0xfffffff0 and len(attest_calls)==before)
    check('active-status-available',call('a6400_uvc_shared_ioctl',0,0x8010f022,0x205000)==0)
    check('active-ioctl-retains-native-reservation',word(guard_sym)==0x80000000 and word(symbols['native_reserved'])==1)
    before=len(events)
    check('active-native-ioctl-remains-excluded-between-calls',call('a6400_uvc_native_gadgetcore_ioctl',0,0x400ce203,0)==0xfffffff0 and len(events)==before)
    check('active-followup-status-reuses-reservation',call('a6400_uvc_shared_ioctl',0,0x8010f022,0x205000)==0)
    put(symbols['control_gate'],1)
    check('active-concurrent-mod-call-rejected',call('a6400_uvc_shared_ioctl',0,0x8010f022,0x205000)==0xfffffff0)
    put(symbols['control_gate'],0)
    put(guard_sym,0);before=len(events)
    check('lost-native-reservation-fails-closed',call('a6400_uvc_shared_ioctl',0,0xe001,0)==0xffffff8c and len(events)==before and word(symbols['pinned'])==1)
    put(guard_sym,0x80000000)
    call('probe_hold',symbols['session'],0x210000,0x700000)
    before=len(events)
    check('held-release-skips-original',call('a6400_uvc_shared_release',0,0)==0xfffffff0 and len(events)==before)
    check('held-stop-skips-probe-clear',call('a6400_uvc_shared_ioctl',0,0xe001,0)==0xfffffff0 and len(events)==before)
    check('held-status-available',call('a6400_uvc_shared_ioctl',0,0x8010f022,0x205000)==0 and struct.unpack('<II',cpu.mem_read(0x205000,8))==(3,1))
    check('held-ioctl-init-rejected',call('a6400_uvc_shared_ioctl',0,0x4038e000,0)==0xfffffff0 and len(events)==before)
    check('held-failures-retain-native-reservation',word(guard_sym)==0x80000000 and word(symbols['native_reserved'])==1)
    # Explicit completed-cleanup fixture, not execution of hardware restoration.
    put(symbols['pinned'],0);put(symbols['owner'],0);call('probe_idle',symbols['session'])
    check('completed-cleanup-releases-reservation',call('a6400_uvc_shared_ioctl',0,0x8010f022,0x205000)==0 and word(guard_sym)==0 and word(symbols['native_reserved'])==0)
    before=len(events)
    check('native-ioctl-dispatch-forwarded',call('a6400_uvc_native_gadgetcore_ioctl',0,0x400ce203,0)==0 and events[-1]=='native-gadgetcore-ioctl')
    put(guard_sym,0x80000000)
    before=len(events)
    check('native-ioctl-held-rejected',call('a6400_uvc_native_gadgetcore_ioctl',0,0x400ce203,0)==0xfffffff0 and len(events)==before)
    put(guard_sym,0)
    def entry_hook_cycle():return call('a6400_uvc_shared_ioctl',0,0xc020f025,0x205000)
    put(0x602b8844,0xe1a0c00d);put(0x604e5098,0x602b8844)
    attest()
    check('entry-hook-cycle-full',entry_hook_cycle()==0 and word(0x602b8844)==0xe1a0c00d and word(0x604e5098)==0x602b8844)
    check('entry-hook-cycle-unpinned',self_ref['count']==0 and word(symbols['entry_lease'])==0)
    check('entry-hook-cycle-repeat',entry_hook_cycle()==0 and word(0x602b8844)==0xe1a0c00d and self_ref['count']==0)
    def entry_hook_pub():return call('a6400_uvc_shared_ioctl',0,0xc020f026,0x205000)
    def entry_hook_ret():return call('a6400_uvc_shared_ioctl',0,0xc020f027,0x205000)
    check('entry-hook-publish-step',entry_hook_pub()==0 and word(0x602b8844)!=0xe1a0c00d and self_ref['count']==1)
    check('entry-hook-published-phase',word(symbols['entry_lease'])==1)
    check('entry-hook-retire-step',entry_hook_ret()==0 and word(0x602b8844)==0xe1a0c00d and self_ref['count']==0)
    check('entry-hook-retired-phase',word(symbols['entry_lease'])==0)
    report=dict(status='offline_module_audit_passed',count=len(checks),checks=checks,
        module_sha256=hashlib.sha256(raw).hexdigest(),module_bytes=len(raw),camera_access=False,loaded=False,
        limitations=['This guard audit checks file-owner/native-reference linkage structurally; dedicated self-ref controls execute the native module_put body separately.',
            'Copy services and original core ioctl/release entries are EXPLICIT RECORDERS for compiled MOD guard tests.',
            'HELD session is an explicit typed fixture; no native hardware failure/recovery is simulated as firmware compatibility.',
            'ACTIVE/IDLE fixtures test reservation lifetime; route-slot fixture does not install a kernel hook or prove quiescence.',
            'Stop attestation calls original sys_ptrace via an explicit recorder; not real tracer/owner authentication in this audit.',
            'Shadow route mutates only a module-owned word; module self-pin is a recorder here, not live native refcount execution.',
            'Cache helper and on_each_cpu dispatch are recorders; compiled per-core callback executes separately. Not physical cache or ingress-drain proof.',
            'No native USB serialization, physical enumeration, PTP controls or sensor frames are proven.'])
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
