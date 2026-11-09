"""Original clear-configuration body with explicit interface/hardware doubles."""
import hashlib
import json
import struct
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA


def main():
    raw = KERNEL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == KERNEL_SHA
    checks = []
    for name, configured, fail_interface, hw_result in [('idle', 0, -1, 0), ('configured', 1, -1, 0), ('interface-failure', 1, 1, 0), ('hardware-failure', 1, -1, -110)]:
        c = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        c.mem_map(0x60108000, (len(raw) + 4095) & ~4095)
        c.mem_write(0x60108000, raw)
        c.mem_map(0x100000, 0x10000)
        gc, gadget, config, interfaces, ops, callback, done = [0x100000 + i * 0x1000 for i in range(7)]
        events, returned = [], []

        def put(a, v):
            c.mem_write(a, struct.pack('<I', v))

        put(gc, gadget)
        c.mem_write(gc + 0x74, bytes([configured]))
        c.mem_write(gc + 0x82, bytes([9]))
        put(gadget + 0x10, ops)
        put(ops + 0x18, callback)
        c.mem_write(config + 2, bytes([3]))
        put(config + 4, interfaces)
        for i in range(3):
            c.mem_write(interfaces + i * 8, bytes([i]))

        def hook(cpu, address, size, unused):
            if address == done:
                returned.append(cpu.reg_read(UC_ARM_REG_R0))
                cpu.emu_stop()
                return
            if address == 0x602bb628:
                events.append('lookup')
                result = config
            elif address == 0x602bb8c8:
                events.append('prepare-stop')
                result = 0
            elif address == 0x602b8f8c:
                interface = cpu.reg_read(UC_ARM_REG_R1)
                events.append(f'stop-interface-{interface}')
                assert c.mem_read(gc + 0x74, 1) == b'\x01'
                result = -1 if interface == fail_interface else 0
            elif address == callback:
                assert cpu.reg_read(UC_ARM_REG_R0) == gadget
                assert cpu.reg_read(UC_ARM_REG_R1) == 1
                assert cpu.reg_read(UC_ARM_REG_R2) == 0
                assert c.mem_read(gc + 0x74, 1) == b'\0'
                assert c.mem_read(gc + 0x82, 1) == b'\0'
                events.append('hardware-reset')
                result = hw_result
            elif 0x602b90cc <= address < 0x602b9178:
                return
            else:
                raise RuntimeError(f'Unexpected execution {address:08x}')
            cpu.reg_write(UC_ARM_REG_R0, result & 0xffffffff)
            cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

        c.hook_add(UC_HOOK_CODE, hook)
        c.reg_write(UC_ARM_REG_R0, gc)
        c.reg_write(UC_ARM_REG_SP, 0x10f000)
        c.reg_write(UC_ARM_REG_LR, done)
        c.emu_start(0x602b90cc, 0xffffffff, count=1000)
        expected = -1 if fail_interface >= 0 or hw_result else 0
        assert returned == [expected & 0xffffffff]
        final_config = c.mem_read(gc + 0x74, 1)[0]
        assert final_config == (1 if fail_interface >= 0 else 0)
        if name == 'idle':
            assert events == []
        elif fail_interface >= 0:
            assert events == ['lookup', 'prepare-stop', 'stop-interface-0', 'stop-interface-1']
        else:
            assert events == ['lookup', 'prepare-stop', 'stop-interface-0', 'stop-interface-1', 'stop-interface-2', 'hardware-reset']
        checks.append(dict(name=name, events=events, result=expected, final_config=final_config))
    out = ROOT / 'artifacts/analysis/uvc-ptp-unconfigure-e0211'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps(dict(status='offline_original_unconfigure_passed', kernel_sha256=KERNEL_SHA, checks=checks, limitations=['Configuration lookup, stop preparation, per-interface stop and hardware reset are explicit service doubles.', 'No actual PTP/UVC callback, lock concurrency, completion or physical teardown is proven.']), indent=2) + '\n')
    print(f'{len(checks)} original unconfigure cases passed')


if __name__ == '__main__':
    main()
