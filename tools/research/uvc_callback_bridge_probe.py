"""Compiled MOD bridge plus original a6400 dispatcher contract controls.

Reference callbacks are explicit recorders, NOT firmware callback bodies. Native
registration masks are explicit fixtures; no physical USB or kernel registration.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE,UC_PROT_READ,UC_PROT_WRITE,UC_PROT_EXEC
from unicorn.arm_const import (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,
    UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,UC_ARM_REG_R8,UC_ARM_REG_R9,
    UC_ARM_REG_R10,UC_ARM_REG_R11,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC,UC_CPU_ARM_CORTEX_A9)

ROOT=Path(__file__).resolve().parents[2]
KERNEL=ROOT/'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
KSHA='12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707'
CTX,REF,VECTOR,REQUEST,MANAGER,RECORD,FRAME=0x200000,0x201000,0x202000,0x203000,0x204000,0x204100,0x204500
RETURN,CALLBACK,HELPERS=0x300000,0x310000,0x320000
REG_OK,REG_FAIL_2ND,UNREG_OK=0x320000,0x320100,0x320200


class Machine:
    def __init__(self,path,kernel):
        self.cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM);self.cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A9)
        self.symbols={};pages={}
        with path.open('rb') as f:
            elf=ELFFile(f)
            for seg in elf.iter_segments():
                if seg['p_type']!='PT_LOAD' or not seg['p_memsz']:continue
                a,b=seg['p_vaddr']&~4095,(seg['p_vaddr']+seg['p_memsz']+4095)&~4095
                flags=seg['p_flags'];perm=(UC_PROT_READ if flags&4 else 0)|(UC_PROT_WRITE if flags&2 else 0)|(UC_PROT_EXEC if flags&1 else 0)
                for p in range(a,b,4096):pages[p]=pages.get(p,0)|perm
            for page in pages:self.cpu.mem_map(page,4096)
            for seg in elf.iter_segments():
                if seg['p_type']=='PT_LOAD' and seg['p_filesz']:self.cpu.mem_write(seg['p_vaddr'],seg.data())
            for page,perm in pages.items():self.cpu.mem_protect(page,4096,perm)
            self.symbols={s.name:s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name}
        self.cpu.mem_map(0x200000,0x6000);self.cpu.mem_map(0x210000,0x4000)
        self.cpu.mem_map(RETURN,4096);self.cpu.mem_write(RETURN,bytes.fromhex('1eff2fe1'))
        self.cpu.mem_map(CALLBACK,4096)
        for i in range(9):self.cpu.mem_write(CALLBACK+i*0x100,bytes.fromhex('1eff2fe1'))
        self.cpu.mem_map(HELPERS,4096)
        for i in range(4):self.cpu.mem_write(HELPERS+i*0x100,bytes.fromhex('1eff2fe1'))
        # Known original code pages, not service replacements.
        self.cpu.mem_map(0x602b8000,0x3000)
        off=0x602b8000-0x60108000;self.cpu.mem_write(0x602b8000,kernel[off:off+0x3000])
        self.cpu.mem_protect(0x602b8000,0x3000,UC_PROT_READ|UC_PROT_EXEC)
        self.events=[];self.stop=RETURN;self.stopped=False
        def hook(cpu,pc,size,context):
            if pc==self.stop:self.stopped=True;cpu.emu_stop();return
            if CALLBACK<=pc<CALLBACK+0x900 and (pc-CALLBACK)%0x100==0:
                self.events.append({'callback':(pc-CALLBACK)//0x100,
                    'arguments':[cpu.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]})
                cpu.reg_write(UC_ARM_REG_R0,0x76543210) # explicit recorder return fixture
            elif HELPERS<=pc<HELPERS+0x400 and (pc-HELPERS)%0x100==0:
                arg0=cpu.reg_read(UC_ARM_REG_R0)
                helper_idx=(pc-HELPERS)//0x100
                self.events.append({'helper':helper_idx,'argument':arg0})
                if pc==REG_FAIL_2ND and len([e for e in self.events if e.get('helper')==1])>=2:
                    cpu.reg_write(UC_ARM_REG_R0,0xfffffff0)
                else:
                    cpu.reg_write(UC_ARM_REG_R0,0)
        self.cpu.hook_add(UC_HOOK_CODE,hook)
        self.cpu.mem_write(VECTOR,b'\x00\x01');self.cpu.mem_write(VECTOR+0x100,b'reference-video\0')
        ref=bytearray(0x3c);struct.pack_into('<I',ref,0,VECTOR+0x100)
        ref[4:6]=b'\x01\x01';struct.pack_into('<I',ref,8,VECTOR);ref[0xc]=2
        struct.pack_into('<I',ref,0x10,0x12345678)
        for i in range(9):struct.pack_into('<I',ref,0x18+i*4,CALLBACK+i*0x100)
        self.cpu.mem_write(REF,bytes(ref))
        self.cpu.mem_write(REQUEST,bytes.fromhex('a181000000001a00'))
        self.cpu.mem_write(MANAGER+4,struct.pack('<I',0x205000))

    def run(self,start,stop=RETURN,registers=()):
        self.stop=stop;self.stopped=False
        for reg,value in registers:self.cpu.reg_write(reg,value)
        self.cpu.reg_write(UC_ARM_REG_SP,0x213f00);self.cpu.reg_write(UC_ARM_REG_LR,RETURN)
        self.cpu.emu_start(start,0xffffffff,count=100000)
        if not self.stopped:raise RuntimeError('Bounded execution did not reach stop')
        return self.cpu.reg_read(UC_ARM_REG_R0)

    def call(self,name,*args):
        regs=[(r,args[i] if i<len(args) else 0) for i,r in enumerate((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3))]
        return self.run(self.symbols[name] if isinstance(name,str) else name,registers=regs)

    def prepare(self):return self.call('a6400_uvc_bridge_prepare',CTX,REF)
    def activate(self):return self.call('a6400_uvc_bridge_activate',CTX,3) # EXPLICIT ack-mask fixture
    def register(self,reg_fn=REG_OK,unreg_fn=UNREG_OK):return self.call('a6400_uvc_bridge_register',CTX,reg_fn,unreg_fn)
    def unregister(self,unreg_fn=UNREG_OK):return self.call('a6400_uvc_bridge_unregister',CTX,unreg_fn)
    def quiesce(self):return self.call('a6400_uvc_bridge_quiesce',CTX)
    def shadow(self,index):return self.call('a6400_uvc_bridge_shadow',CTX,index)
    def callback(self,index,which):return struct.unpack('<I',self.cpu.mem_read(self.shadow(index)+0x10+which*4,4))[0]
    def request(self,interface):self.cpu.mem_write(REQUEST+4,struct.pack('<H',interface))

    def original_class(self,index,wire=None,entity=0):
        interface=index if wire is None else wire
        shadow=self.shadow(index);self.request(interface | (entity<<8))
        self.cpu.mem_write(RECORD,struct.pack('<I',shadow))
        return self.run(0x602ba05c,0x602ba090,[(UC_ARM_REG_R7,RECORD),(UC_ARM_REG_R8,1),
            (UC_ARM_REG_R10,interface),(UC_ARM_REG_R5,REQUEST),(UC_ARM_REG_R4,MANAGER)])

    def original_start(self,index):
        shadow=self.shadow(index);self.cpu.mem_write(RECORD,struct.pack('<I',shadow))
        self.cpu.mem_write(FRAME+0xc,struct.pack('<I',0x12345678))
        self.cpu.mem_write(MANAGER+0x11,b'\x02');self.cpu.mem_write(REQUEST+1,bytes([index]))
        return self.run(0x602b8ecc,0x602b8f00,[(UC_ARM_REG_R0,REQUEST),(UC_ARM_REG_R4,RECORD),
            (UC_ARM_REG_R5,MANAGER),(UC_ARM_REG_R9,1),(UC_ARM_REG_R11,FRAME)])

    def original_stop(self,index):
        self.cpu.mem_write(RECORD,struct.pack('<I',self.shadow(index)))
        return self.run(0x602b8d70,0x602b8d84,[(UC_ARM_REG_R4,RECORD)])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--reference-wire-object',type=Path,
        help='Optional hash-checked E0156 MOD reference for real callback-entry slices')
    args=parser.parse_args();out=args.report_dir.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):parser.error('Report must remain under artifacts')
    out.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((args.build_dir/'manifest.json').read_text())
    for relative,sha in manifest['files'].items():
        if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()!=sha:raise ValueError('Build identity changed')
    kernel=KERNEL.read_bytes()
    if hashlib.sha256(kernel).hexdigest()!=KSHA:raise ValueError('Original kernel identity mismatch')
    path=args.build_dir/'uvc_callback_bridge.elf';checks=[]
    def check(name,condition):
        if not condition:raise AssertionError(name)
        checks.append(name)
    def fresh():return Machine(path,kernel)
    m=fresh();check('prepare',m.prepare()==0)
    for index in (0,1):
        s=m.shadow(index);d=bytes(m.cpu.mem_read(s,0x34))
        check('shadow-interface-'+str(index),d[4]==1 and d[5]==index)
        m.run(0x602b8644,0x602b865c,[(UC_ARM_REG_R6,s)])
        check('original-registration-guards-'+str(index),m.stopped)
    check('inactive-class-rejected',m.call(m.callback(0,7),m.shadow(0),REQUEST,0x205000)==2 and not m.events)
    check('partial-registration-mask-rejected',m.call('a6400_uvc_bridge_activate',CTX,1)==0xffffffea)
    check('activate-fixture',m.activate()==0)
    for index in (0,1):
        before=len(m.events);value=m.original_class(index)
        event=m.events[-1]
        check('original-class-route-'+str(index),len(m.events)==before+1 and event['callback']==7 and event['arguments'][:3]==[REF,REQUEST,0x205000] and value==0x76543210)
    before=len(m.events);m.request(42)
    check('wrong-interface-rejected',m.call(m.callback(0,7),m.shadow(0),REQUEST,0x205000)==2 and len(m.events)==before)
    m.request(0)
    check('unknown-shadow-rejected',m.call(m.callback(0,7),0x205100,REQUEST,0x205000)==2 and len(m.events)==before)
    original=bytes(m.cpu.mem_read(REF+0x34,4));m.cpu.mem_write(REF+0x34,struct.pack('<I',CALLBACK+0x900))
    check('changed-reference-callback-rejected',m.call(m.callback(0,7),m.shadow(0),REQUEST,0x205000)==2 and len(m.events)==before)
    check('stale-error',m.call('a6400_uvc_bridge_last_error',CTX)==0xffffff8c)
    m.cpu.mem_write(REF+0x34,original)
    m.original_start(0);check('control-interface-start-suppressed',len(m.events)==before)
    m.original_start(1)
    check('primary-start-forwarded',len(m.events)==before+1 and m.events[-1]['callback']==0 and m.events[-1]['arguments']==[REF,2,1,0x12345678])
    check('alternate-state-translated',bytes(m.cpu.mem_read(REF+0x14,1))==b'\x01')
    before=len(m.events);m.original_start(1);check('duplicate-start-rejected',len(m.events)==before)
    check('retire-while-started-rejected',m.call('a6400_uvc_bridge_retire',CTX,0)==0xfffffff0)
    m.original_stop(0);check('control-interface-stop-suppressed',len(m.events)==before)
    m.original_stop(1);check('primary-stop-forwarded',len(m.events)==before+1 and m.events[-1]['callback']==1)
    check('retire-while-registered-rejected',m.call('a6400_uvc_bridge_retire',CTX,3)==0xfffffff0)
    s=m.shadow(0);callback=m.callback(0,7)
    check('retire-quiescent-fixture',m.call('a6400_uvc_bridge_retire',CTX,0)==0)
    before=len(m.events)
    check('late-class-rejected',m.call(callback,s,REQUEST,0x205000)==2 and len(m.events)==before)
    check('context-reuse-after-retire',m.prepare()==0)
    # Physical feeder registers VC as primary: VS still owns the Bulk endpoint.
    m_vs=fresh();m_vs.cpu.mem_write(REF+5,b'\x00')
    check('vc-primary-prepare',m_vs.prepare()==0)
    check('vc-primary-register',m_vs.register()==0)
    m_vs.original_start(0)
    check('zero-endpoint-vc-start-suppressed',not m_vs.events or all('callback' not in e for e in m_vs.events))
    m_vs.original_start(1)
    check('secondary-vs-start-forwarded',m_vs.events[-1].get('callback')==0 and m_vs.events[-1]['arguments']==[REF,2,1,0x12345678])
    before_vs=len(m_vs.events);m_vs.original_stop(0)
    check('vc-stop-does-not-stop-vs',len(m_vs.events)==before_vs)
    check('secondary-vs-quiesce',m_vs.quiesce()==0 and m_vs.events[-1].get('callback')==1)
    check('secondary-vs-unregister',m_vs.unregister()==0)
    m_pad=fresh();check('padded-count-prepare',m_pad.prepare()==0)
    check('padded-count-register',m_pad.register()==0)
    m_pad.call(m_pad.callback(1,0),m_pad.shadow(1),2,0x68971d01,0x12345678)
    check('packed-count-upper-bytes-ignored',m_pad.events[-1].get('arguments')==[REF,2,1,0x12345678])
    check('padded-count-unregister',m_pad.unregister()==0)
    # Shared PTP/UVC candidate: shadows use actual wire interfaces 1/2.
    # Native reference class classifier must be separately patched for 1/2;
    # callbacks here remain explicit recorders and preserve the setup pointer.
    m_map=fresh();m_map.cpu.mem_write(VECTOR,b'\x01\x02')
    check('wire12-prepare',m_map.prepare()==0)
    check('wire12-register-fixture',m_map.register()==0)
    for index,wire in [(0,1),(1,2)]:
        check('wire12-shadow-'+str(wire),bytes(m_map.cpu.mem_read(m_map.shadow(index)+5,1))==bytes([wire]))
        for entity in (0,2):
            before_map=len(m_map.events)
            result=m_map.original_class(index,wire,entity)
            event=m_map.events[-1]
            check('wire12-original-route-'+str(wire)+'-entity-'+str(entity),
                len(m_map.events)==before_map+1 and event.get('callback')==7 and
                event['arguments'][:3]==[REF,REQUEST,0x205000] and result==0x76543210)
            check('wire12-request-unchanged-'+str(wire)+'-entity-'+str(entity),
                bytes(m_map.cpu.mem_read(REQUEST+4,2))==bytes([wire,entity]))
    before_map=len(m_map.events);m_map.request(0)
    check('wire12-ptp-zero-rejected',m_map.call(m_map.callback(0,7),m_map.shadow(0),REQUEST,0x205000)==2 and len(m_map.events)==before_map)
    m_map.request(2)
    check('wire12-wrong-shadow-rejected',m_map.call(m_map.callback(0,7),m_map.shadow(0),REQUEST,0x205000)==2 and len(m_map.events)==before_map)
    m_map.original_start(1)
    check('wire12-vs-start-forwarded',m_map.events[-1].get('callback')==0)
    before_map=len(m_map.events);m_map.original_stop(0)
    check('wire12-vc-stop-does-not-stop-vs',len(m_map.events)==before_map)
    check('wire12-unregister-quiesces-fixture',m_map.unregister()==0)
    check('wire12-quiesce-stops-reference',any(e.get('callback')==1 for e in m_map.events))
    # Registration lifecycle and shutdown/quiescence controls:
    m_reg=fresh();check('reg-prepare',m_reg.prepare()==0)
    check('register-rollback-on-failure',m_reg.register(reg_fn=REG_FAIL_2ND)==0xfffffff0)
    check('rollback-shadow0-unregistered',len([e for e in m_reg.events if e.get('helper')==2 and e.get('argument')==m_reg.shadow(0)])==1)
    m_auto=fresh();check('auto-prepare',m_auto.prepare()==0)
    check('auto-register-success',m_auto.register()==0)
    m_auto.original_start(1)
    check('unregister-active-auto-quiesces',m_auto.unregister()==0)
    check('auto-quiesce-stopped-callback',any(e.get('callback')==1 for e in m_auto.events))
    m_q=fresh();check('quiesce-prepare',m_q.prepare()==0);check('quiesce-register',m_q.register()==0)
    m_q.original_start(1)
    check('explicit-quiesce-stops',m_q.quiesce()==0 and m_q.events[-1].get('callback')==1)
    check('unregister-quiesced-success',m_q.unregister()==0)
    invalid=[('wrong-count',REF+0xc,b'\x01'),('duplicate-interfaces',VECTOR+1,b'\x00'),
        ('unknown-primary',REF+5,b'\x02'),('missing-start',REF+0x18,bytes(4)),
        ('missing-stop',REF+0x1c,bytes(4)),('missing-class',REF+0x34,bytes(4))]
    for name,address,data in invalid:
        q=fresh();q.cpu.mem_write(address,data);check(name,q.prepare()==0xffffffea)
    if args.reference_wire_object:
        reference_path=args.reference_wire_object.resolve()
        reference_manifest=json.loads((reference_path.parent/'manifest.json').read_text())
        reference_raw=reference_path.read_bytes()
        if hashlib.sha256(reference_raw).hexdigest()!=reference_manifest['direct_wire_mod']['sha256']:
            raise ValueError('Wire reference MOD identity mismatch')
        from tools.research.build_uvc_ptp_adapter import REF as REFERENCE_FILE,REF_SHA
        original=REFERENCE_FILE.read_bytes()
        if hashlib.sha256(original).hexdigest()!=REF_SHA:raise ValueError('Original reference identity mismatch')
        if len(original)!=len(reference_raw) or [i for i,(a,b) in enumerate(zip(original,reference_raw)) if a!=b]!=[0x11a0,0x141c,0x141e]:
            raise ValueError('Reference MOD has unexpected changes')
        import io
        reference_text=ELFFile(io.BytesIO(reference_raw)).get_section_by_name('.text').data()
        # Real kernel dispatch -> compiled MOD bridge -> real MOD reference
        # class callback -> reference classifier. STOP before service calls;
        # no callback return or queue/allocator success is fabricated.
        for index,wire in [(0,1),(1,2)]:
            for entity in (0,2):
                q=fresh();q.cpu.mem_write(VECTOR,b'\x01\x02')
                q.cpu.mem_map(0x700000,0x10000);q.cpu.mem_write(0x700000,reference_text)
                q.cpu.mem_protect(0x700000,0x10000,UC_PROT_READ|UC_PROT_EXEC)
                q.cpu.mem_write(REF+0x34,struct.pack('<I',0x7017b0))
                check('real-wire-prepare-'+str(wire)+'-'+str(entity),q.prepare()==0)
                check('real-wire-register-fixture-'+str(wire)+'-'+str(entity),q.register()==0)
                request=bytes([0xa1,0x81,0,1,wire,entity,26,0])
                q.cpu.mem_write(REQUEST,request)
                shadow=q.shadow(index);q.cpu.mem_write(RECORD,struct.pack('<I',shadow))
                end=0x7016f8 if entity else (0x701410 if wire==1 else 0x7016a4)
                q.run(0x602ba05c,end,[(UC_ARM_REG_R7,RECORD),(UC_ARM_REG_R8,1),
                    (UC_ARM_REG_R10,wire),(UC_ARM_REG_R5,REQUEST),(UC_ARM_REG_R4,MANAGER)])
                check('real-wire-native-path-'+str(wire)+'-'+str(entity),q.stopped)
                check('real-wire-original-setup-unchanged-'+str(wire)+'-'+str(entity),bytes(q.cpu.mem_read(REQUEST,8))==request)
                # GET helper r6 is the unchanged setup pointer.
                check('real-wire-original-setup-pointer-'+str(wire)+'-'+str(entity),q.cpu.reg_read(UC_ARM_REG_R6)==REQUEST)
    report={'status':'passed','checks':checks,'count':len(checks),'kernel_sha256':KSHA,
        'bridge_elf_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'reference_wire_object_sha256':(hashlib.sha256(reference_raw).hexdigest()
                                       if args.reference_wire_object else None),
        'probe_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'recorder_events':m.events,'camera_access':False,'deployable':False,
        'limitations':['Reference callbacks are EXPLICIT recorders, not original video callback bodies.',
            'Registered masks3/0 are EXPLICIT lifecycle fixtures, not real kernel acknowledgements.',
            'Original kernel slices execute routing/guard instructions only, not USB enumeration.',
            'With --reference-wire-object, real MOD reference callback entry/classifier runs only to a pre-service stop; it does not return successfully.',
            'Native registration, rollback, endpoint/DMA and module-unload lifetime remain unimplemented/unverified.']}
    (out/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(len(checks),'compiled-bridge/original-dispatch contract controls passed; no physical compatibility claim')


if __name__=='__main__':main()
