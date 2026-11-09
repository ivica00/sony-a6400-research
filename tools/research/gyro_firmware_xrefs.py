"""Locate Thumb PIC references to sensor diagnostics without executing firmware."""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import re
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB


def scan(path):
    blob = path.read_bytes()
    if blob[4:8] != b'ORIL':
        raise ValueError('Expected original LIRO image')
    base = struct.unpack_from('<I', blob, 12)[0] - 0x44
    terms = [b'api_get_gyro_act_sens_rsrc', b'api_get_acc_act_sens_rsrc',
             b'[ACTSENS_R_I]', b'Gyro Data >>', b'gyro_sync_id:',
             b'[    LC->LENS] GyroStart']
    targets = [(match.start(), term.decode()) for term in terms
               for match in re.finditer(re.escape(term), blob)]
    decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    decoder.skipdata = True
    recent = deque(maxlen=12)
    hits = []
    for address, size, mnemonic, operands in decoder.disasm_lite(blob[:0x8c0000], base):
        if mnemonic in ('add', 'add.w') and operands.endswith(', pc'):
            register = operands.split(',')[0]
            loads = [item for item in recent if item[2] in ('ldr', 'ldr.w')
                     and item[3].startswith(register + ', [pc, #')]
            if loads:
                load_address, _, _, load_operands = loads[-1]
                displacement = int(load_operands.split('#')[1].split(']')[0], 0)
                literal = ((load_address + 4) & ~3) + displacement - base
                if 0 <= literal <= len(blob) - 4:
                    value = struct.unpack_from('<I', blob, literal)[0]
                    resolved = (value + address - base + 4) & 0xffffffff
                    for target, term in targets:
                        if resolved == target:
                            hits.append(dict(term=term, string_offset=hex(target),
                                             add=hex(address), load=hex(load_address),
                                             literal_offset=hex(literal)))
        recent.append((address, size, mnemonic, operands))
    return dict(source=str(path), sha256=hashlib.sha256(blob).hexdigest(),
                image_base=hex(base), scan_code_prefix_bytes=min(len(blob), 0x8c0000),
                scope='Static candidate xrefs; not model-specific execution proof', hits=hits)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = scan(args.image)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
