"""Original per-interface STOP ownership and ordering; services are recorders."""
import hashlib
import json
import struct
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA


def main():
    raw = KERNEL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == KERNEL_SHA
    checks = []
    for name, active, requested, matching_config in [('active-match', 1, 1, 1), ('inactive', 0, 1, 1), ('other-interface', 1, 2, 1), ('other-config', 1, 1, 2)]:
        c = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        c.mem_map(0x60108000, (len(raw) + 4095) & ~4095)
        c.mem_write(0x60108000, raw)
        c.mem_map(0x100000, 0x10000)
        gc, record, descriptor, ep_list, callback, endpoint, done = [0x100000 + i * 0x1000 for i in range(7)]
        events, returned = [], []

        def put(a, v):
            c.mem_write(a, struct.pack('<I', v))

        c.mem_write(gc + 0x74, b'\x01')
        put(gc + 0x78, record + 4)
        put(record, descriptor)
        put(record + 4, gc + 0x78)
        c.mem_write(record + 0xc, b'\x01')
        put(record + 0x10, ep_list)
        c.mem_write(record + 0x14, bytes([active]))
        c.mem_write(descriptor + 4, bytes([matching_config, 1]))
        put(descriptor + 0x14, callback)
        put(ep_list, endpoint)

        def hook(cpu, address, size, unused):
            r0, r1 = cpu.reg_read(UC_ARM_REG_R0), cpu.reg_read(UC_ARM_REG_R1)
            if address == done:
                returned.append(r0)
                cpu.emu_stop()
                return
            if address == 0x602bd450:
                result = 2  # Explicit ordinary PC Remote GCW state.
            elif address == callback:
                assert r0 == descriptor and c.mem_read(record + 0x14, 1) == b'\0'
                events.append('callback-after-active-clear')
                result = 0x12345678  # Void callback result is ignored by original code.
            elif address == 0x602ba968:
                assert r0 == gc and r1 == endpoint
                events.append('endpoint-release')
                result = 0
            elif address == 0x601b1664:
                assert r0 == ep_list
                events.append('free-endpoint-list')
                result = 0
            elif address == 0x602ba85c:
                assert r0 == gc and r1 == requested
                events.append('disable-interface-endpoints')
                result = 0
            elif 0x602b8f8c <= address < 0x602b90cc:
                return
            else:
                raise RuntimeError(f'Unexpected execution {address:08x}')
            cpu.reg_write(UC_ARM_REG_R0, result)
            cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

        c.hook_add(UC_HOOK_CODE, hook)
        c.reg_write(UC_ARM_REG_R0, gc)
        c.reg_write(UC_ARM_REG_R1, requested)
        c.reg_write(UC_ARM_REG_SP, 0x10f000)
        c.reg_write(UC_ARM_REG_LR, done)
        c.emu_start(0x602b8f8c, 0xffffffff, count=1000)
        expected = ['callback-after-active-clear', 'endpoint-release', 'free-endpoint-list', 'disable-interface-endpoints'] if name == 'active-match' else ['disable-interface-endpoints']
        assert returned == [0] and events == expected, (name, events)
        checks.append(dict(name=name, events=events))
    out = ROOT / 'artifacts/analysis/uvc-ptp-interface-stop-e0213'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps(dict(status='offline_original_interface_stop_passed', kernel_sha256=KERNEL_SHA, checks=checks, limitations=['Registry, GCW state, callback, endpoint release, free and hardware disable are explicit fixtures/recorders.', 'Callback body, special GCW states 5/6, wildcard fallback drivers, physical concurrency and complete teardown remain unproven.']), indent=2) + '\n')
    print(f'{len(checks)} original interface STOP cases passed')


if __name__ == '__main__':
    main()
