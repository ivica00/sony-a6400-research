"""Run original CUsb queue/worker code with explicit pthread service doubles."""
import argparse
import hashlib
import io
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from tools.research.arm_plt import resolve_arm_plt
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT

LIB = ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib/libInfraUsbCmn.so'
SHA = '5338bafbb545ebc223fac15c9253a41ac9fe49c01fe32c73af40c3fb50eec0a6'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args(); out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'): parser.error('Output must be under artifacts')
    raw = LIB.read_bytes(); assert hashlib.sha256(raw).hexdigest() == SHA
    elf = ELFFile(io.BytesIO(raw)); symbols = elf.get_section_by_name('.dynsym')
    names = {s.name: s['st_value'] for s in symbols.iter_symbols()}
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(0, 0x20000)
    for seg in elf.iter_segments():
        if seg['p_type'] == 'PT_LOAD': cpu.mem_write(seg['p_vaddr'], seg.data())
    for section in elf.iter_sections():
        if section['sh_type'] == 'SHT_REL':
            table = elf.get_section(section['sh_link'])
            for rel in section.iter_relocations():
                if rel['r_info_type'] in (21,22):
                    s = table.get_symbol(rel['r_info_sym'])
                    if s['st_value']: cpu.mem_write(rel['r_offset'], struct.pack('<I', s['st_value']))
    cpu.mem_map(0x200000, 0x10000); cpu.mem_map(0x300000, 4096); cpu.mem_map(0x400000, 0x10000)
    obj, ring, message, done = 0x200000, 0x201000, 0x202000, 0x300000
    checks, events = [], []
    state = dict(locked=False, stop_request=False, stop_callback=False)
    def word(a): return struct.unpack('<I', cpu.mem_read(a,4))[0]
    def put(a,v): cpu.mem_write(a,struct.pack('<I',v))
    def check(n,p):
        if not p: raise AssertionError(n)
        checks.append(n)
    # Resolve each used PLT stub from actual ARM instructions and relocations.
    # Thumb interworking veneers make index * constant-stride guesses invalid.
    plt_targets=resolve_arm_plt(elf)
    expected={0x7b10:'_ZN4CUsb7requestEP8CUSB_MES',0x7a34:'_ZN4CUsb8que_pushEPS_P8CUSB_MES',
        0x7f28:'_ZN4CUsb7que_popEPS_',0x7b94:'pthread_mutex_lock',0x7af4:'pthread_mutex_unlock',
        0x7c24:'pthread_cond_signal',0x7f1c:'getpid',0x80a8:'pthread_setcancelstate',
        0x81ac:'_ZN7CUsbSvc11stop_gadgetEPvhPFS0_S0_S0_hiE'}
    for address,name in expected.items():
        check('actual-plt-'+hex(address),plt_targets[address]['name']==name)
    def ret(v=0):
        cpu.reg_write(UC_ARM_REG_R0,v); cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
    def hook(c,a,size,_):
        if a == done: c.emu_stop(); return
        if a == 0x7b10:
            if state['stop_request']:
                state['message'] = bytes(c.mem_read(c.reg_read(UC_ARM_REG_R1),32))
                c.emu_stop(); return
            c.reg_write(UC_ARM_REG_PC, names['_ZN4CUsb7requestEP8CUSB_MES']); return
        if a in (0x7a34,0x7f28):
            if not state['locked']: raise AssertionError('queue operation without fixture lock')
            c.reg_write(UC_ARM_REG_PC,names['_ZN4CUsb8que_pushEPS_P8CUSB_MES' if a==0x7a34 else '_ZN4CUsb7que_popEPS_']); return
        if a == 0x7b94:
            assert not state['locked']; assert c.reg_read(UC_ARM_REG_R0)==obj+0x40
            state['locked']=True;events.append('pthread-lock-double');ret();return
        if a == 0x7af4:
            assert state['locked'];state['locked']=False;events.append('pthread-unlock-double');ret();return
        if a in (0x792c,0x80a8): ret();return  # log/cancellation explicit doubles
        if a == 0x7f1c:ret(149);return  # getpid explicit fixture
        if a == 0x7c24:events.append('condition-signal-double');ret();return
        if a == 0x81ac:
            state['direct_stop_arguments']=[c.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
            events.append('original-stop-gadget-direct-boundary');c.emu_stop();return
        if state['stop_callback'] and a == (state['callback']&~1):
            state['callback_locked']=state['locked'];state['callback_argument']=c.reg_read(UC_ARM_REG_R0)
            events.append('original-worker-callback-boundary');c.emu_stop();return
        if not any(x<=a<y for x,y in [(0x8432,0x85da),(0x9e00,0x9f90)]):
            raise RuntimeError(f'Unexpected execution {a:08x}')
    def guard(c,access,a,size,value,_):
        if not any(x<=a and a+size<=y for x,y in [(obj,obj+0x200),(ring,ring+128),(message,message+32),(0x400000,0x410000)]):
            raise RuntimeError(f'Unexpected write {a:08x}')
    cpu.hook_add(UC_HOOK_CODE,hook);cpu.hook_add(UC_HOOK_MEM_WRITE,guard)
    def call(a,*values):
        for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),values):cpu.reg_write(r,v)
        cpu.reg_write(UC_ARM_REG_SP,0x40f000);cpu.reg_write(UC_ARM_REG_LR,done)
        cpu.emu_start(a|1,0xffffffff,count=20000)
        return cpu.reg_read(UC_ARM_REG_R0)
    put(obj+0x14,ring);cpu.mem_write(obj+0x18,bytes([0,0,4]))
    state['stop_request']=True
    call(0x9ed9,obj,0x12345678,7,0x300101)
    payload=state['message'];state['stop_request']=False
    callback=struct.unpack_from('<I',payload,8)[0]
    callback_names=[n for n,v in names.items() if v==callback]
    check('start-message-object',struct.unpack_from('<I',payload)[0]==obj)
    check('start-message-user',struct.unpack_from('<I',payload,12)[0]==0x12345678)
    check('start-message-argument-byte',payload[16]==7)
    check('start-message-completion',struct.unpack_from('<I',payload,20)[0]==0x300101)
    check('start-message-native-callback',callback==names['_ZN7CUsbSvc12createGadgetEP8CUSB_MES'])
    cpu.mem_write(message,payload)
    check('request-success',call(names['_ZN4CUsb7requestEP8CUSB_MES'],obj,message)==0)
    check('request-releases-lock',not state['locked'])
    check('request-copies-32-bytes',bytes(cpu.mem_read(ring,32))==bytes(cpu.mem_read(message,32)))
    check('request-advances-tail',bytes(cpu.mem_read(obj+0x18,2))==bytes([0,1]))
    check('request-signals-worker','condition-signal-double' in events)
    state.update(stop_callback=True,callback=callback)
    call(names['_ZN4CUsb12proc_serviceEPv'],obj)
    check('worker-reaches-original-callback',events[-1]=='original-worker-callback-boundary')
    check('worker-unlocks-before-callback',state['callback_locked'] is False)
    check('worker-passes-ring-slot',state['callback_argument']==ring)
    check('worker-advances-head',bytes(cpu.mem_read(obj+0x18,2))==bytes([1,1]))
    # Original ring boundaries: empty, full, and wrap, no pthread operations.
    state['stop_callback']=False
    check('empty-pop-null',call(names['_ZN4CUsb7que_popEPS_'],obj)==0)
    cpu.mem_write(obj+0x18,bytes([0,3,4]))
    before=bytes(cpu.mem_read(ring,128))
    check('full-push-rejected',call(names['_ZN4CUsb8que_pushEPS_P8CUSB_MES'],obj,message)==12)
    check('full-push-preserves-ring',bytes(cpu.mem_read(ring,128))==before)
    cpu.mem_write(obj+0x18,bytes([2,3,4]))
    check('wrap-push-success',call(names['_ZN4CUsb8que_pushEPS_P8CUSB_MES'],obj,message)==0)
    check('wrap-tail-zero',bytes(cpu.mem_read(obj+0x19,1))==b'\0')
    check('wrap-slot-copy',bytes(cpu.mem_read(ring+96,32))==bytes(cpu.mem_read(message,32)))
    # The same library also exposes stop outside the queue. Its body directly
    # calls stop_gadget after changing service state; no worker identity check.
    put(obj+0x9c,0xabc1);put(obj+0xa0,0xabc2);put(obj+0x98,3)
    put(0x40f000,0x300101)
    state['stop_callback']=False
    call(names['_ZN7CUsbSvc4stopE11__USBIF_DIDPvhPFS1_S1_S1_hiE'],obj,0xabc1,0x12345678,7)
    check('stop-calls-gadget-directly',events[-1]=='original-stop-gadget-direct-boundary')
    check('stop-transitions-state-to-four',word(obj+0x98)==4)
    check('stop-direct-arguments',state['direct_stop_arguments']==[obj,0x12345678,7,0x300101])
    check('stop-does-not-enqueue',bytes(cpu.mem_read(obj+0x18,2))==bytes([2,0]))
    put(obj+0x98,2);before=len(events)
    check('stop-wrong-state-rejected',call(names['_ZN7CUsbSvc4stopE11__USBIF_DIDPvhPFS1_S1_S1_hiE'],obj,0xabc1,0,0)==6 and len(events)==before)
    put(obj+0x98,3)
    check('stop-wrong-handle-rejected',call(names['_ZN7CUsbSvc4stopE11__USBIF_DIDPvhPFS1_S1_S1_hiE'],obj,0xabcf,0,0)==11)
    report=dict(status='original_service_queue_checks_passed',count=len(checks),checks=checks,events=events,
        library_sha256=SHA,probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        callback=hex(callback),callback_names=callback_names,camera_access=False,
        queue_layout=dict(buffer_offset=0x14,head_offset=0x18,tail_offset=0x19,capacity_offset=0x1a,
            slot_bytes=32,mutex_offset=0x40,condition_offset=0x58),
        limitations=['Object, ring and initial queue indices are explicit fixtures.',
            'Pthread/log/cancellation/getpid services are explicit doubles, not scheduler proof.',
            'Native createGadget is a stop boundary, not executed here.',
            'Direct stop_gadget is a stop boundary, not executed here; caller scheduling remains unknown.',
            'One worker execution does not prove all callers or absence of concurrent workers.'])
    out.mkdir(parents=True,exist_ok=True);(out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
