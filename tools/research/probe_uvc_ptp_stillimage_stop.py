"""Execute original PTP STOP and event adapter; explicit kernel service recorders."""
import hashlib
import json
import struct
import argparse
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--completion-chain',action='store_true')
    chain=parser.parse_args().completion_chain
    source = ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/kmod/usbg_stillimage.ko'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest == 'd4843c6abac908881ef5a96fd570fb345f766fff9ee562413f5f63e9cc7e0ff9'
    with source.open('rb') as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name('.symtab')
        symbols = {s.name: s['st_value'] for s in symtab.iter_symbols() if s.name}
        text = bytearray(elf.get_section_by_name('.text').data())
        for r in elf.get_section_by_name('.rel.text').iter_relocations():
            symbol = symtab.get_symbol(r['r_info_sym'])
            if r['r_info_type'] == 2 and isinstance(symbol['st_shndx'], int) and elf.get_section(symbol['st_shndx']).name == '.text':
                offset = r['r_offset']
                value = struct.unpack_from('<I', text, offset)[0]
                struct.pack_into('<I', text, offset, value + 0x100000 + symbol['st_value'])
            elif chain and r['r_info_type']==2 and isinstance(symbol['st_shndx'],int) and elf.get_section(symbol['st_shndx']).name=='.bss':
                offset=r['r_offset'];value=struct.unpack_from('<I',text,offset)[0]
                struct.pack_into('<I',text,offset,value+0x20d000+symbol['st_value'])
        reloc = {r['r_offset']: symtab.get_symbol(r['r_info_sym']).name for r in elf.get_section_by_name('.rel.text').iter_relocations()}
    checks = []
    scenarios=[(q,cancelled) for q in (0,-12) for cancelled in ((0,1) if chain else (0,))]
    for queue_result,cancelled in scenarios:
        c = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        c.mem_map(0x100000, (len(text) + 4095) & ~4095)
        c.mem_write(0x100000, bytes(text))
        c.mem_map(0x200000, 0x10000)
        ctx, extra, endpoints, ops, free_callback, done = [0x200000 + i * 0x1000 for i in range(6)]
        events, returned = [], []
        locks=set()

        def put(a, v):
            c.mem_write(a, struct.pack('<I', v & 0xffffffff))

        put(ctx, 0xabcdef01)
        put(ctx + 8, 0x98765432)  # User STOP callback identifier.
        put(ctx+0x20,0x76543210)  # Transfer completion user callback identifier.
        put(0x20d000,ctx)
        put(ctx + 0xa4, endpoints)
        for i in range(3):
            ep = 0x206000 + i * 0x100
            put(endpoints + i * 4, ep)
            put(ep + 8, ops)
        put(ops + 0xc, free_callback)
        put(ops+0x14,0x20b000)
        for i in range(3):
            info=0x20a000+i*8
            c.mem_write(info+2,bytes([1 if i==0 else 0]))
            put(info+4,0x209000)
        put(0x209020,512);put(0x20902c,-108)
        put(extra+0x24c,cancelled)
        requests=[0x209000,0x209100,0x209200] if chain else [0x301,0x302,0x303]
        for offset, value in zip((0x18,0x20,0x28),requests):
            put(extra + offset, value)

        def hook(cpu, address, size, unused):
            args = [cpu.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
            if address == done:
                returned.append(True)
                cpu.emu_stop()
                return
            if chain and address==0x20b000:
                assert args[:2]==[0x206000,0x209000]
                assert extra+0x258 in locks and extra+0x2a0 not in locks
                events.append(['synchronous-read-completion'])
                cpu.reg_write(UC_ARM_REG_PC,0x100000+symbols['sicd_data_read_comp'])
                return
            if address == free_callback:
                events.append(['free-request', args[0], args[1]])
                result = 0
                return_address = cpu.reg_read(UC_ARM_REG_LR)
            else:
                name = reloc.get(address - 0x100000)
                if not name:
                    if 0x100aa4 <= address < 0x100b70 or 0x100270 <= address < 0x100338 or (chain and any(0x100000+symbols[n]<=address<0x100000+symbols[n]+size for n,size in [('sicd_ep_dequeue_all',80),('sicd_ep_dequeue',120),('sicd_request_stop',24),('sicd_set_requesting_flag',84),('sicd_data_read_comp',160)])):
                        return
                    raise RuntimeError(f'Unexpected instruction {address:08x}')
                return_address = address + 4
                if name == 'sicd_call_user_cb' or (chain and name in ('sicd_ep_dequeue_all','sicd_ep_dequeue','sicd_request_stop','sicd_set_requesting_flag')):
                    cpu.reg_write(UC_ARM_REG_LR, return_address)
                    cpu.reg_write(UC_ARM_REG_PC, 0x100000 + symbols[name])
                    return
                if name == 'sicd_get_this':
                    result = ctx
                elif name == 'sicd_get_this_ex':
                    result = extra
                elif chain and name=='sicd_get_ep_info':
                    assert args[0] in (0x206000,0x206100,0x206200)
                    result=0x20a000+((args[0]-0x206000)//0x100)*8
                elif name in ('_mutex_lock', '_mutex_unlock'):
                    if chain:
                        if name=='_mutex_lock':
                            assert args[0] not in locks, ('recursive-lock',hex(args[0]))
                            locks.add(args[0])
                        else:
                            assert args[0] in locks
                            locks.remove(args[0])
                    events.append([name, args[0]])
                    result = 0
                elif name in ('sicd_ep_dequeue_all', 'usbg_cmn_clear_ep_list', 'sicd_set_status'):
                    events.append([name, args[0]])
                    result = 0
                elif name == '__memzero':
                    assert args[:2] == [extra + 0x14, 0x18]
                    c.mem_write(args[0], bytes(args[1]))
                    events.append(['zero-request-fields'])
                    result = 0
                elif name == 'usb_event_add_queue':
                    sp = cpu.reg_read(UC_ARM_REG_SP)
                    stack = struct.unpack('<II', c.mem_read(sp, 8))
                    if chain and args[1]==0x76543210:
                        assert args[:3]==[0,0x76543210,0xabcdef01] and args[3]==(4 if cancelled else 2) and stack[0]==8
                        assert struct.unpack('<Ii',c.mem_read(stack[1],8))==(512,-108)
                        events.append(['usb-event-completion'])
                    else:
                        assert args == [0, 0x98765432, 0xabcdef01, 0] and stack == (0, 0)
                        events.append(['usb-event-stop'])
                    result = queue_result
                else:
                    raise RuntimeError(f'Unexpected service {name}')
            cpu.reg_write(UC_ARM_REG_R0, result & 0xffffffff)
            cpu.reg_write(UC_ARM_REG_PC, return_address)

        c.hook_add(UC_HOOK_CODE, hook)
        c.reg_write(UC_ARM_REG_SP, 0x20f000)
        c.reg_write(UC_ARM_REG_LR, done)
        c.emu_start(0x100000 + symbols['core_cb_stop'], 0xffffffff, count=2000)
        names = [e[0] for e in events]
        assert returned
        if chain:
            assert not locks and names.count('synchronous-read-completion')==1
            assert names.index('usb-event-completion')<names.index('free-request')<names.index('usb-event-stop')
            assert c.mem_read(extra+0x1e,1)==b'\0'
            assert struct.unpack('<I',c.mem_read(extra+0x24c,4))[0]==0
        else:
            assert names == ['_mutex_lock', 'sicd_ep_dequeue_all', 'free-request', 'free-request', 'free-request', 'zero-request-fields', 'usbg_cmn_clear_ep_list', '_mutex_unlock', '_mutex_lock', 'sicd_set_status', '_mutex_unlock', 'usb-event-stop']
        assert [e[2] for e in events if e[0] == 'free-request'] == [requests[1],requests[0],requests[2]]
        checks.append(dict(queue_result=queue_result,cancelled=cancelled,events=events,returned=True))
    out = ROOT / ('artifacts/analysis/uvc-ptp-completion-locks-e0216' if chain else 'artifacts/analysis/uvc-ptp-stillimage-stop-e0214')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps(dict(status='offline_original_ptp_stop_passed', completion_chain=chain, source=str(source.relative_to(ROOT)), source_sha256=digest, checks=checks, limitations=['Original STOP/event adapter execute; chain mode additionally executes original dequeue chain, requesting-flag update and read completion through an explicit synchronous endpoint service fixture.', 'Getters, mutexes, free, status, zeroing and event enqueue are explicit fixtures/recorders; no real kernel locking, DMA, IRQ concurrency, queue implementation or physical teardown.']), indent=2) + '\n')
    print(f'{len(checks)} original PTP STOP cases passed')


if __name__ == '__main__':
    main()
