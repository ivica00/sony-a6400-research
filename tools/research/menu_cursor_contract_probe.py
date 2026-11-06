"""Execute captured original cursor getter on explicit constructed controls.

This verifies a narrow read contract, not camera navigation or a service reply.
"""
import json
import struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

ROOT = Path(__file__).resolve().parents[2]


def run(code, index):
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    start = 0x61248d6
    uc.mem_map(0x6124000, 0x2000)
    uc.mem_write(start, code)
    model, item, table, stack, end = 0x8300000, 0x8310000, 0x8320000, 0x8330000, 0x8340000
    for address in (model, item, table, stack, end):
        uc.mem_map(address, 0x1000)
    known = set()
    reads = []
    def supply(address, data):
        uc.mem_write(address, data)
        known.update(range(address, address + len(data)))
    supply(model + 12, struct.pack('<I', table))
    supply(item + 8, struct.pack('<I', 7))
    supply(table + 3 * 7, bytes([index]))
    def read(_uc, _access, address, size, _value, _data):
        if not all(byte in known for byte in range(address, address + size)):
            raise ValueError('Original getter read unsupplied bytes: ' + hex(address))
        reads.append(dict(address=hex(address), size=size))
    def write(_uc, _access, address, size, _value, _data):
        if not stack <= address < address + size <= stack + 0x1000:
            raise ValueError('Unexpected original getter write')
        known.update(range(address, address + size))
    uc.hook_add(UC_HOOK_MEM_READ, read)
    uc.hook_add(UC_HOOK_MEM_WRITE, write)
    uc.reg_write(UC_ARM_REG_R0, model)
    uc.reg_write(UC_ARM_REG_R1, item)
    uc.reg_write(UC_ARM_REG_SP, stack + 0xff0)
    uc.reg_write(UC_ARM_REG_LR, end | 1)
    uc.emu_start(start | 1, end, count=100)
    if uc.reg_read(UC_ARM_REG_PC) != end or uc.reg_read(UC_ARM_REG_R0) != index:
        raise ValueError('Getter did not return constructed cursor index')
    return dict(constructed_index=index, returned_index=uc.reg_read(UC_ARM_REG_R0), reads=reads)


def main():
    capture = ROOT / 'artifacts/hardware/native-menu-cursor-internal-contracts.json'
    code = bytes.fromhex(json.loads(capture.read_text())['0x61248d6']['code'])[:0x62]
    # The retained original window ends this function at pop {r4,r7,pc}.
    if code[-2:] != bytes.fromhex('90bd'):
        raise ValueError('Unexpected original cursor getter boundary')
    report = dict(scope='Original ARM getter with explicit constructed inputs; no hardware navigation proof',
                  source=str(capture.relative_to(ROOT)), controls=[run(code, index) for index in (0, 1, 5)])
    destination = ROOT / 'artifacts/analysis/menu-cursor-contract-probe.json'
    destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(destination)


if __name__ == '__main__':
    main()
