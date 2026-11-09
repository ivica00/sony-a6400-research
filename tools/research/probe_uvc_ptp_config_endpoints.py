"""Execute original SET_CONFIGURATION endpoint-number admission loop offline."""
import hashlib
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4, UC_ARM_REG_FP, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
from tools.research.build_uvc_ptp_descriptor_candidate import ROOT, KERNEL, KERNEL_SHA


def main():
    raw = KERNEL.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == KERNEL_SHA
    checks = []
    for video, expected in [(0x82, 'conflict'), (0x84, 'accepted'), (0x81, 'conflict'), (0x83, 'conflict')]:
        c = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        c.mem_map(0x60108000, (len(raw) + 4095) & ~4095)
        c.mem_write(0x60108000, raw)
        c.mem_map(0x100000, 0x10000)
        gc, gadget, ops, config, interfaces, request, callback = [0x100000 + i * 0x1000 for i in range(7)]
        events = []
        outcome = []

        def put(a, v):
            c.mem_write(a, struct.pack('<I', v))

        put(gc, gadget)
        put(gadget + 0x10, ops)
        put(ops + 0x18, callback)
        c.mem_write(config, bytes([1, 0, 3, 0]))
        put(config + 4, interfaces)
        for index, endpoints in enumerate([(0x81, 0x02, 0x83), (), (video,)]):
            alternate = 0x107000 + index * 0x100
            endpoint_base = 0x108000 + index * 0x100
            c.mem_write(interfaces + index * 8, bytes([index, 1, 0, 0]))
            put(interfaces + index * 8 + 4, alternate)
            c.mem_write(alternate, bytes([0, len(endpoints), 0, 0]))
            put(alternate + 4, endpoint_base)
            for j, address in enumerate(endpoints):
                c.mem_write(endpoint_base + j * 20, bytes([address, 2, 0, 2, 0, 3, 0, 0]))
        c.mem_write(request, bytes([0, 9, 1, 0, 0, 0, 0, 0]))

        def hook(cpu, address, size, unused):
            if address in (0x602b9898, 0x602ba42c):
                outcome.append('conflict' if address == 0x602b9898 else 'accepted')
                cpu.emu_stop()
                return
            if address == 0x602bb628:
                result = config  # Explicit configuration lookup fixture.
            elif address == 0x602b90cc:
                result = 0  # Explicit old-configuration teardown double.
            elif address == callback:
                events.append(cpu.reg_read(UC_ARM_REG_R1))
                result = 0  # Explicit hardware endpoint admission double.
            elif 0x602b9650 <= address <= 0x602b9894:
                return
            else:
                raise RuntimeError(f'Unexpected execution {address:08x}')
            cpu.reg_write(UC_ARM_REG_R0, result)
            cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

        c.hook_add(UC_HOOK_CODE, hook)
        for reg, value in [(UC_ARM_REG_R1, request), (UC_ARM_REG_R4, gc), (UC_ARM_REG_FP, 0x10f000), (UC_ARM_REG_SP, 0x10e000)]:
            c.reg_write(reg, value)
        c.emu_start(0x602b9650, 0xffffffff, count=10000)
        assert outcome == [expected], (video, outcome)
        checks.append(dict(video_endpoint=hex(video), outcome=outcome[0], hardware_operations=events))
    out = ROOT / 'artifacts/analysis/uvc-ptp-config-endpoints-e0210'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps(dict(status='offline_original_endpoint_admission_passed', kernel_sha256=KERNEL_SHA, checks=checks, limitations=['Starts at SET_CONFIGURATION branch with explicit stack/context fixtures.', 'Configuration lookup, teardown and hardware admission are doubles.', 'Accepted means endpoint-number scan completed, not complete USB configuration or physical enumeration.']), indent=2) + '\n')
    print(f'{len(checks)} original endpoint admission cases passed')


if __name__ == '__main__':
    main()
