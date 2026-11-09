"""Verify the specific refresh GEN_Icon import against both original ELF files."""
import hashlib
import json
import struct
from tools.camera_debugger import connect
from tools.research.remote_elf import RemoteElf32, debugger_reader
from tools.research.active_menu_snapshot_probe import HW


def main():
    address, base = 0x15f2bad4, 0x155e6000
    name = '_ZN8GEN_Icon8setImageEjb'
    with connect() as d:
        source = RemoteElf32(debugger_reader(d, '/usr/lib/viewUnified2.so'))
        target = RemoteElf32(debugger_reader(d, '/usr/lib/libObj.so'))
        matches = []
        for section in source.sections:
            if section[1] != 9:
                continue
            if section[9] != 8:
                raise ValueError('Unexpected relocation entry size')
            raw = source.exact(section[4], section[5])
            for offset in range(0, len(raw), 8):
                slot, info = struct.unpack_from('<II', raw, offset)
                if slot == address-base:
                    matches.append(info)
        if len(matches) != 1 or matches[0] & 255 != 22:
            raise ValueError('Expected unique R_ARM_JUMP_SLOT')
        symbol = struct.unpack('<IIIBBH', source.exact(source.symbols[4]+(matches[0]>>8)*16, 16))
        encoded = name.encode()+b'\0'
        if symbol[5] or source.exact(source.strings[4]+symbol[0], len(encoded)) != encoded:
            raise ValueError('Unexpected original imported symbol')
        definition = target.resolve(name)
        pointer = 0x5d18000+definition['value']
        live = d.memory(149, address, 4)
        if struct.unpack('<I', live)[0] != pointer:
            raise ValueError('Live import differs from original defined function')
        entry = pointer & ~1
        code = d.memory(149, entry, min(256, definition['size']))
        if code != target.virtual(entry-0x5d18000, len(code)):
            raise ValueError('Imported function code differs from original')
    report = dict(import_name=name, relocation_type=22, relocation_verified=True,
        defined_symbol=definition, records=[dict(address=hex(address), data=live.hex(), code=False),
        dict(address=hex(entry), data=code.hex(), code=True, source_equal=True,
             sha256=hashlib.sha256(code).hexdigest())])
    (HW/'native-refresh-icon-import-e0130.json').write_text(json.dumps(report, indent=2))
    print('Original icon import and target code verified:', hex(pointer))


if __name__ == '__main__':
    main()
