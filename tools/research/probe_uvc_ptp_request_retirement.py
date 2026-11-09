"""Original request giveback and endpoint-list retirement; no live hardware."""
import argparse, hashlib, json, struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output-dir', type=Path, required=True)
    out = p.parse_args().output_dir.resolve()
    if not out.is_relative_to(ROOT / 'artifacts'):
        p.error('Output must be under artifacts')
    raw = KERNEL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == KERNEL_SHA
    c = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    c.mem_map(0x60108000, (len(raw) + 4095) & ~4095)
    c.mem_write(0x60108000, raw)
    c.mem_map(0x100000, 0x10000)
    c.mem_map(0x200000, 0x10000)
    dwc, ep, req, req2, callback, done = [0x100000 + i * 0x1000 for i in range(6)]
    state, checks = {}, []

    def put(a, v):
        c.mem_write(a, struct.pack('<I', v & 0xffffffff))

    def word(a):
        return struct.unpack('<I', c.mem_read(a, 4))[0]

    services = {0x603c691c: 'unlock', 0x6012bee0: 'migrate-enable',
                0x6012c0ac: 'migrate-disable', 0x603c68f4: 'lock'}

    def hook(cpu, a, size, unused):
        if a == done:
            state['returned'] = True
            cpu.emu_stop()
            return
        result = 0
        if a in services:
            state['events'].append(services[a])
            if a in (0x603c691c, 0x603c68f4):
                assert cpu.reg_read(UC_ARM_REG_R0) == dwc + 0x70
        elif a == 0x602b529c:
            state['events'].append('unmap-double')
        elif a == 0x602b03d8:
            assert cpu.reg_read(UC_ARM_REG_R0) == dwc
            assert cpu.reg_read(UC_ARM_REG_R1) == state.get('endpoint', 2)
            state['events'].append('stop-transfer-double')
        elif a == callback:
            r = cpu.reg_read(UC_ARM_REG_R1)
            assert r in (req, req2) and cpu.reg_read(UC_ARM_REG_R0) == ep
            assert state['events'][-2:] == ['unlock', 'migrate-enable']
            assert word(r + 0x48) == 0
            assert word(r + 0x34) != ep + 0x24 and word(r + 0x34) != ep + 0x2c
            state['events'].append(['completion-double', hex(r), word(r + 0x2c)])
        elif (0x602affb8 <= a < 0x602b00f8 or 0x602b0484 <= a < 0x602b04f4
              or 0x602b1a3c <= a < 0x602b1b30 or 0x602b26ec <= a < 0x602b283c
              or 0x602b2ad0 <= a < 0x602b2b40):
            return
        else:
            raise RuntimeError(f'Unexpected execution {a:08x}')
        cpu.reg_write(UC_ARM_REG_R0, result)
        cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

    c.hook_add(UC_HOOK_CODE, hook)
    for name, active, pending, initial in [('empty', 0, 0, -115), ('pending', 0, 1, -115),
                                            ('active', 1, 0, -115), ('both', 1, 1, -115),
                                            ('preserve-error', 0, 1, -5)]:
        c.mem_write(dwc, bytes(0x6000))
        put(ep + 0x48, dwc)
        c.mem_write(ep + 0x54, bytes([2]))
        for head, r, present in [(ep + 0x2c, req, active), (ep + 0x24, req2, pending)]:
            put(head, r + 0x34 if present else head)
            put(head + 4, r + 0x34 if present else head)
            if present:
                put(r + 0x34, head)
                put(r + 0x38, head)
                put(r + 0x1c, callback)
                put(r + 0x2c, initial)
                put(r + 0x48, 0x1234)
        state.clear()
        state.update(returned=False, events=[])
        c.reg_write(UC_ARM_REG_R0, dwc)
        c.reg_write(UC_ARM_REG_R1, ep)
        c.reg_write(UC_ARM_REG_SP, 0x20f000)
        c.reg_write(UC_ARM_REG_LR, done)
        c.emu_start(0x602b0484, 0xffffffff, count=2000)
        assert state['returned']
        assert word(ep + 0x24) == ep + 0x24 and word(ep + 0x2c) == ep + 0x2c
        completions = [e for e in state['events'] if isinstance(e, list)]
        expected = [hex(r) for r, present in [(req, active), (req2, pending)] if present]
        assert [e[1] for e in completions] == expected
        assert all(e[2] == ((-108 if initial == -115 else initial) & 0xffffffff) for e in completions)
        assert state['events'].count('stop-transfer-double') == active
        checks.append(dict(name=name, events=list(state['events'])))
    # Execute full original EP0 disable, then try the original internal queue
    # body with pullup's admission field already zero. No queue-service double.
    for endpoint in (0, 1):
        c.mem_write(dwc, bytes(0x7000))
        mmio = dwc + 0x6000
        put(dwc + 0x2b4, mmio)
        put(dwc + 0x170, 0)
        put(0x604c92d0 + 0x1c, 0)
        put(mmio + 0x620, 0xff)
        put(ep + 0x48, dwc)
        put(ep + 0x4c, 1)
        c.mem_write(ep + 0x54, bytes([endpoint]))
        for head, r in [(ep + 0x2c, req), (ep + 0x24, req2)]:
            put(head, r + 0x34)
            put(head + 4, r + 0x34)
            put(r + 0x34, head)
            put(r + 0x38, head)
            put(r + 0x1c, callback)
            put(r + 0x2c, -115)
        state.clear()
        state.update(returned=False, events=[], endpoint=endpoint)
        c.reg_write(UC_ARM_REG_R0, ep)
        c.reg_write(UC_ARM_REG_SP, 0x20f000)
        c.reg_write(UC_ARM_REG_LR, done)
        c.emu_start(0x602b1a3c, 0xffffffff, count=2000)
        assert state['returned'] and c.reg_read(UC_ARM_REG_R0) == 0
        assert word(ep + 0x24) == ep + 0x24 and word(ep + 0x2c) == ep + 0x2c
        assert word(ep + 0x4c) == 0 and word(ep + 0x1c) == 0
        assert word(mmio + 0x620) == 0xff & ~(1 << endpoint)
        assert len([e for e in state['events'] if isinstance(e, list)]) == 2
        before = bytes(c.mem_read(req2, 0x54))
        c.reg_write(UC_ARM_REG_R0, ep)
        c.reg_write(UC_ARM_REG_R1, req2)
        c.reg_write(UC_ARM_REG_SP, 0x20f000)
        c.reg_write(UC_ARM_REG_LR, done)
        c.emu_start(0x602b26ec, 0xffffffff, count=100)
        assert c.reg_read(UC_ARM_REG_R0) == (-108) & 0xffffffff
        assert bytes(c.mem_read(req2, 0x54)) == before
        assert word(ep + 0x24) == ep + 0x24
        checks.append(dict(name=f'ep{endpoint}-disable-and-closed-admission', events=list(state['events'])))
    for name, descriptor, occupied, admission, expected in [
            ('public-disabled', 0, False, 1, -108),
            ('public-occupied', 1, True, 1, -16),
            ('public-admission-closed', 1, False, 0, -108),
            ('public-admitted', 1, False, 1, 0)]:
        c.mem_write(dwc, bytes(0x6000))
        put(ep + 0x48, dwc)
        put(ep + 0x1c, descriptor)
        put(dwc + 0x170, admission)
        put(ep + 0x24, req + 0x34 if occupied else ep + 0x24)
        put(ep + 0x28, req + 0x34 if occupied else ep + 0x24)
        before = bytes(c.mem_read(req2, 0x54))
        state.clear()
        state.update(returned=False, events=[])
        c.reg_write(UC_ARM_REG_R0, ep)
        c.reg_write(UC_ARM_REG_R1, req2)
        c.reg_write(UC_ARM_REG_SP, 0x20f000)
        c.reg_write(UC_ARM_REG_LR, done)
        c.emu_start(0x602b2ad0, 0xffffffff, count=200)
        assert state['returned'] and c.reg_read(UC_ARM_REG_R0) == expected & 0xffffffff
        assert state['events'] == ['migrate-disable', 'lock', 'unlock', 'migrate-enable']
        if expected:
            assert bytes(c.mem_read(req2, 0x54)) == before
        else:
            assert word(ep + 0x24) == req2 + 0x34
            assert word(req2 + 0x2c) == (-115) & 0xffffffff
        checks.append(dict(name=name, result=expected, events=list(state['events'])))
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps(dict(
        status='offline_original_request_retirement_passed', kernel_sha256=KERNEL_SHA, checks=checks,
        limitations=['Endpoint/request lists are explicit fixtures; request DMA flag bit2 is clear.',
                     'Hardware transfer stop, unmap, completion, locks and migration are doubles.',
                     'No reentrant completion, request producer exclusion or physical DMA completion proof.']), indent=2) + '\n')
    print(f'{len(checks)} original request retirement cases passed')


if __name__ == '__main__':
    main()
