"""Original ARM OSAL unregister/wait/wake bodies; no live module loading."""
import argparse,hashlib,io,json,struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--acknowledgement',action='store_true',help='Also execute original kernel wait_cb and finish_callback')
    args=p.parse_args();out=args.output_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):p.error('Output must be under artifacts')
    source=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/osal_uipc.ko'
    raw=source.read_bytes();sha='3743275bc964a2804b80cde4f589f60876b795fbeeccd3cbf2c18a0da2dc8567';assert hashlib.sha256(raw).hexdigest()==sha
    elf=ELFFile(io.BytesIO(raw));sym=elf.get_section_by_name('.symtab');sections={};cursor=0x100000
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);cpu.mem_map(cursor,0x80000);writable=[]
    for i,s in enumerate(elf.iter_sections()):
        if not s['sh_flags']&2 or not s['sh_size']:continue
        cursor=(cursor+4095)&~4095;sections[i]=cursor
        if s['sh_type']!='SHT_NOBITS':cpu.mem_write(cursor,s.data())
        if s['sh_flags']&1:writable.append((cursor,cursor+s['sh_size']))
        cursor+=s['sh_size']
    assert cursor<0x180000
    cpu.mem_map(0x200000,0x10000);cpu.mem_map(0x300000,0x10000);cpu.mem_map(0x400000,0x10000)
    imports={};addresses={}
    def get(s):
        if s['st_shndx']=='SHN_UNDEF':
            if s.name not in imports:imports[s.name]=0x300000+len(imports)*4
            return imports[s.name]
        if s['st_shndx']=='SHN_ABS':return s['st_value']
        return sections[s['st_shndx']]+s['st_value']
    for s in sym.iter_symbols():
        if s.name and (s['st_shndx'] in sections or s['st_shndx'] in ('SHN_UNDEF','SHN_ABS')):addresses[s.name]=get(s)
    for rsec in elf.iter_sections():
        if rsec['sh_type']!='SHT_REL' or rsec['sh_info'] not in sections:continue
        for r in rsec.iter_relocations():
            target=sections[rsec['sh_info']]+r['r_offset'];old=struct.unpack('<I',cpu.mem_read(target,4))[0]
            symbol=get(sym.get_symbol(r['r_info_sym']));kind=r['r_info_type']
            if kind==2:value=(old+symbol)&0xffffffff
            elif kind==28:
                addend=(old&0xffffff)<<2
                if addend&(1<<25):addend-=1<<26
                delta=symbol+addend-target;assert delta%4==0 and -(1<<25)<=delta<(1<<25)
                value=(old&0xff000000)|((delta>>2)&0xffffff)
            else:raise RuntimeError('Unsupported allocated relocation '+str(kind))
            cpu.mem_write(target,struct.pack('<I',value))
    text=sections[next(i for i,s in enumerate(elf.iter_sections()) if s.name=='.text')]
    ctx,cb,task,other=0x200000,0x201000,0x202000,0x203000
    done=0x30f000;head=struct.unpack('<I',cpu.mem_read(text+0x28d8,4))[0]+0x20c
    checks=[];events=[];state={}
    def check(n,v):
        if not v:raise AssertionError(n)
        checks.append(n)
    def word(a):return struct.unpack('<I',cpu.mem_read(a,4))[0]
    def put(a,v):cpu.mem_write(a,struct.pack('<I',v&0xffffffff))
    def ret(v=0):cpu.reg_write(UC_ARM_REG_R0,v&0xffffffff);cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
    service={v:k for k,v in imports.items()}
    for name in ('osal_lock','osal_unlock'):service[addresses[name]]=name
    def hook(c,a,size,_):
        if a==done:c.emu_stop();return
        if a==addresses['free_fblock']:
            check('free-double-expected-object-'+state['case'],c.reg_read(UC_ARM_REG_R0)==cb)
            events.append('free-double');ret();return
        name=service.get(a)
        if name=='memset':
            dst=c.reg_read(UC_ARM_REG_R0);n=c.reg_read(UC_ARM_REG_R1);size=c.reg_read(UC_ARM_REG_R2)
            assert n==0 and size==12;c.mem_write(dst,bytes(size));ret(dst);return
        if name in ('__copy_from_user','__copy_to_user'):
            dst=c.reg_read(UC_ARM_REG_R0);src=c.reg_read(UC_ARM_REG_R1);n=c.reg_read(UC_ARM_REG_R2)
            assert n==16;c.mem_write(dst,bytes(c.mem_read(src,n)));events.append(name+'-double');ret();return
        if name in ('osal_lock','osal_unlock'):
            events.append([name,c.reg_read(UC_ARM_REG_R0)]);ret();return
        if name=='schedule':
            state['saved']=c.context_save();state['resume']=c.reg_read(UC_ARM_REG_LR)
            events.append('schedule-boundary');c.emu_stop();return
        if name=='wake_up_process':events.append(['wake-double',c.reg_read(UC_ARM_REG_R0)]);ret();return
        if name=='printk' and args.acknowledgement:events.append('diagnostic-double');ret();return
        if name:raise RuntimeError('Unexpected service '+name)
        if not any(x<=a<y for x,y in [(text+0x2f3c,text+0x2ff8),(text+0x27a0,text+0x28d8),
                                     (text+0x28e0,text+0x2954),(text+0x2b24,text+0x2b58),
                                     *([(text+0xe8c,text+0x10d8),(text+0x4154,text+0x42c8),
                                        (text+0x2330,text+0x23a0),(text+0x2d10,text+0x2ee8)] if args.acknowledgement else [])]):
            raise RuntimeError(f'Unexpected execution {a:08x}')
    def guard(c,access,a,size,value,_):
        if not any(x<=a and a+size<=y for x,y in [*writable,(ctx,ctx+0x100),(cb,cb+0x20),(task,task+0x108),
                                               *([(0x204000,0x204108),(0x205000,0x205100),(0x206000,0x206010)] if args.acknowledgement else []),
                                               (0x400000,0x410000)]):
            raise RuntimeError(f'Unexpected write {a:08x}')
    cpu.hook_add(UC_HOOK_CODE,hook);cpu.hook_add(UC_HOOK_MEM_WRITE,guard)
    def call(offset,r0,r1=0,stack=0x40f000):
        cpu.reg_write(UC_ARM_REG_R0,r0);cpu.reg_write(UC_ARM_REG_R1,r1);cpu.reg_write(UC_ARM_REG_SP,stack);cpu.reg_write(UC_ARM_REG_LR,done)
        cpu.emu_start(text+offset,0xffffffff,count=20000);return cpu.reg_read(UC_ARM_REG_R0)
    def prepare(case,count,tid):
        state.clear();state['case']=case;events.clear();cpu.mem_write(ctx,bytes(0x100));cpu.mem_write(cb,bytes(0x20))
        put(ctx+0x18,cb);put(cb+0x10,tid);cpu.mem_write(cb+12,bytes([count,0]));put(head,0)
        put(0x40e00c,task);put(task+0x104,42);put(task+8,other);put(other,0)
        put(word(text+0x2b58),3)  # Explicit native global allocation-count fixture.
    prepare('inactive',0,99)
    check('inactive-unregister-success',call(0x2f3c,ctx,cb)==0)
    check('inactive-clears-slot',word(ctx+0x18)==0)
    check('inactive-no-schedule','schedule-boundary' not in events)
    check('inactive-native-free-decrements-counter',word(word(text+0x2b58))==2)
    prepare('self',1,42)
    check('self-unregister-success',call(0x2f3c,ctx,cb)==0)
    check('self-unregister-does-not-wait','schedule-boundary' not in events)
    check('self-still-active-at-free',bytes(cpu.mem_read(cb+12,1))==b'\1' and 'free-double' in events)
    check('self-native-free-decrements-counter',word(word(text+0x2b58))==2)
    prepare('other',1,99);call(0x2f3c,ctx,cb)
    check('other-unregister-pauses-before-schedule',events[-1]=='schedule-boundary')
    check('other-not-freed-before-completion','free-double' not in events and word(ctx+0x18)==cb)
    waiter=word(head)
    check('other-registers-stack-waiter',0x400000<=waiter<0x410000 and word(waiter+4)==cb and word(waiter+8)==task)
    check('other-marks-retiring',bytes(cpu.mem_read(cb+13,1))[0]&2==2)
    saved,resume=state['saved'],state['resume']
    # Explicit external completion fixture: refcount becomes zero. Original
    # wake helper, not a host-written waiter algorithm, then removes/wakes it.
    cpu.mem_write(cb+12,b'\0');call(0x28e0,cb,stack=0x40b000)
    check('wake-unlinks-waiter',word(head)==0 and word(waiter+4)==0)
    check('wake-targets-waiting-task',['wake-double',task] in events)
    cpu.context_restore(saved);cpu.reg_write(UC_ARM_REG_PC,resume)
    cpu.emu_start(resume,0xffffffff,count=20000)
    check('other-unregister-completes-after-wake',cpu.reg_read(UC_ARM_REG_PC)==done and cpu.reg_read(UC_ARM_REG_R0)==0)
    check('other-frees-and-clears-after-wake',events[-1]=='free-double' and word(ctx+0x18)==0)
    prepare('interrupted',1,99);call(0x2f3c,ctx,cb)
    saved,resume=state['saved'],state['resume'];waiter=word(head);before=len(events)
    call(0x28e0,cb,stack=0x40b000)
    check('active-wake-does-not-remove-waiter',word(head)==waiter and word(waiter+4)==cb and len(events)==before)
    put(other,1)  # Explicit signal-pending fixture, not a real signal delivery.
    cpu.context_restore(saved);cpu.reg_write(UC_ARM_REG_PC,resume)
    cpu.emu_start(resume,0xffffffff,count=20000)
    check('interrupted-unregister-returns-retry',cpu.reg_read(UC_ARM_REG_PC)==done and cpu.reg_read(UC_ARM_REG_R0)==0xfffffc03)
    check('interrupted-preserves-active-slot',word(ctx+0x18)==cb and bytes(cpu.mem_read(cb+12,1))==b'\1')
    check('interrupted-does-not-free','free-double' not in events)
    check('interrupted-removes-stack-waiter',word(head)==0)
    check('interrupted-clears-retiring-bit',bytes(cpu.mem_read(cb+13,1))[0]&2==0)
    check('interrupted-native-allocation-counter-unchanged',word(word(text+0x2b58))==3)
    if args.acknowledgement:
        prepare('acknowledged',1,99);call(0x2f3c,ctx,cb)
        waiting,resume=state['saved'],state['resume']
        owner,user,ack_task,message=0x205000,0x206000,0x204000,0x207000
        cpu.mem_write(owner,bytes(0x100));cpu.mem_write(user,bytes(16))
        put(owner+0x3c,cb);put(owner+0x40,message)
        put(0x40a008,0xffffffff);put(0x40a00c,ack_task)
        put(ack_task+8,other);put(ack_task+0x104,99)
        cpu.mem_write(cb+14,struct.pack('<H',13))
        lookup=word(text+0x23a0);put(lookup+4+13*4,ctx)
        put(owner+0x38,task)
        cpu.reg_write(UC_ARM_REG_R2,owner)
        check('wrong-worker-task-rejected',call(0xe8c,0,user,stack=0x40b000)==0xffffffea)
        check('wrong-worker-preserves-pending-callback',word(owner+0x3c)==cb and bytes(cpu.mem_read(cb+12,1))==b'\1')
        put(owner+0x38,0);put(user+12,4)
        cpu.reg_write(UC_ARM_REG_R2,owner)
        check('out-of-range-worker-index-rejected',call(0xe8c,0,user,stack=0x40b000)==0xffffffea)
        check('bad-index-does-not-complete-callback',word(owner+0x3c)==cb and bytes(cpu.mem_read(cb+12,1))==b'\1')
        put(user+12,0)
        before=len(events)
        cpu.reg_write(UC_ARM_REG_R2,owner)
        call(0xe8c,0,user,stack=0x40b000)
        check('ack-pauses-waiting-for-next-work',events[-1]=='schedule-boundary')
        check('ack-copies-native-input',events[before]=='__copy_from_user-double')
        check('ack-clears-previous-worker-slot',word(owner+0x3c)==0)
        check('ack-original-finish-decrements-active-count',bytes(cpu.mem_read(cb+12,1))==b'\0')
        check('ack-original-finish-wakes-unregister',['wake-double',task] in events[before:])
        check('ack-preserves-registration-until-waiter-resumes',word(ctx+0x18)==cb and 'free-double' not in events)
        check('ack-binds-worker-to-native-task',word(owner+0x38)==ack_task)
        cpu.context_restore(waiting);cpu.reg_write(UC_ARM_REG_PC,resume)
        cpu.emu_start(resume,0xffffffff,count=20000)
        check('ack-unregister-returns-success',cpu.reg_read(UC_ARM_REG_PC)==done and cpu.reg_read(UC_ARM_REG_R0)==0)
        check('ack-unregister-frees-after-original-finish',word(ctx+0x18)==0 and events[-1]=='free-double')
    report=dict(status='original_kernel_unregister_boundaries_passed',count=len(checks),checks=checks,events=events,
        module_sha256=sha,acknowledgement=args.acknowledgement,
        acknowledgement_profile='async callback; empty next-work queue; queue message-release flag clear' if args.acknowledgement else None,
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),camera_access=False,
        limitations=['Relocatable original ARM sections linked offline; no module loader or camera access.',
            'Queue/callback/current task/refcount and completion are explicit fixtures.',
            'Locks, free_fblock and wake task are service doubles; schedule stops execution.',
            'Original free_cb executes through atomic decrement; final free_fblock allocator is not executed.',
            'Native scheduling, actual user copy services, final allocator and message ownership paths remain unproven.'])
    out.mkdir(parents=True,exist_ok=True);(out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
