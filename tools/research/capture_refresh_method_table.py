"""Verify a narrow live method table against original ELF symbols/relocations.

The runtime mapping is writable. Equality to the relocated original is checked
for every word; this is not an assertion that the mapping is immutable.
"""
import hashlib
import json
import struct
from tools.camera_debugger import connect
from tools.research.remote_elf import RemoteElf32, debugger_reader
from tools.research.active_menu_snapshot_probe import HW


def main():
    base, address, size = 0x5d18000, 0x70546e8, 64
    with connect() as debugger:
        elf = RemoteElf32(debugger_reader(debugger, '/usr/lib/libObj.so'))
        original = elf.virtual(address-base, size)
        live = debugger.memory(149, address, size)
        expected = bytearray(original)
        relocations = {}
        for section in elf.sections:
            if section[1] != 9:
                continue
            if section[9] != 8:
                raise ValueError('Unexpected REL entry size')
            raw = elf.exact(section[4], section[5])
            for offset in range(0, len(raw), 8):
                target, info = struct.unpack_from('<II', raw, offset)
                if address-base <= target < address-base+size:
                    if target in relocations or (target-(address-base)) % 4:
                        raise ValueError('Overlapping/unaligned relocation')
                    relocations[target] = (info & 255, info >> 8)
        checks = []
        for offset in range(0, size, 4):
            target = address-base+offset
            kind, index = relocations[target]
            addend = struct.unpack_from('<I', original, offset)[0]
            symbol_value = None
            if kind == 23 and index == 0:
                result = base+addend
            elif kind == 2:
                symbol = struct.unpack('<IIIBBH', elf.exact(elf.symbols[4]+index*16, 16))
                if not symbol[5] or symbol[3] & 15 != 2:
                    raise ValueError('Expected locally defined function symbol')
                symbol_value = symbol[1]
                result = base+symbol_value+addend
            else:
                raise ValueError('Unverified relocation type')
            struct.pack_into('<I', expected, offset, result & 0xffffffff)
            checks.append(dict(target=hex(target+base), type=kind, symbol=index,
                               symbol_value=symbol_value, addend=addend, expected=hex(result)))
        if live != expected:
            raise ValueError('Live method table differs from original relocated ELF')
    record = dict(address=hex(address), data=live.hex(), code=False,
        module='/usr/lib/libObj.so', module_base=hex(base),
        original_file=original.hex(), relocation_verified=True,
        mapping_immutable=False, sha256=hashlib.sha256(live).hexdigest(), checks=checks)
    (HW/'native-refresh-method-table-e0129.json').write_text(json.dumps(record, indent=2))
    print('16 live method-table words match original ELF relocations; no writes')


if __name__ == '__main__':
    main()
