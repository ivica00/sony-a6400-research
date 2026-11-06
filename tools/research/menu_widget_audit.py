"""Preserved Sony menu-widget virtual-method audit; no camera access."""
import io
import json
import struct
import hashlib
from pathlib import Path
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / 'firmware/extracted_a6400/firmware.tar_unpacked/0700_part_image/dev/nflasha15_unpacked/lib'


def main():
    raw = (LIB / 'viewUnified2.so').read_bytes()
    elf = ELFFile(io.BytesIO(raw))
    def read(address, count):
        segments = [p for p in elf.iter_segments() if p['p_type'] == 'PT_LOAD'
                    and p['p_vaddr'] <= address and address+count <= p['p_vaddr']+p['p_filesz']]
        if len(segments) != 1:
            raise ValueError('Ambiguous or unbacked ELF address')
        segment = segments[0]
        start = address - segment['p_vaddr']
        return segment.data()[start:start+count]
    def word(address):
        return struct.unpack('<I', read(address, 4))[0]
    # Original constructor LDR r4 literal / ADD r4,pc / LDR r3,[r4,r3]
    # at 0x56c932, 0x56c93e, 0x56c948; literals 0x56ca64/0x56ca68.
    if read(0x56c93e, 2) != bytes.fromhex('7c44') or read(0x56c948, 2) != bytes.fromhex('e358'):
        raise ValueError('Constructor anchor mismatch')
    got_slot = 0x56c942 + word(0x56ca64) + word(0x56ca68)
    vtable = word(got_slot) + 8
    slots = []
    for section in elf.iter_sections():
        if not isinstance(section, RelocationSection):
            continue
        symbols = elf.get_section(section['sh_link'])
        for relocation in section.iter_relocations():
            offset = relocation['r_offset'] - vtable
            if 0 <= offset < 0x1ac:
                slots.append({'offset': hex(offset), 'relocation_type': relocation['r_info_type'],
                              'symbol': symbols.get_symbol(relocation['r_info_sym']).name,
                              'original_word': hex(word(relocation['r_offset']))})
    result = {'scope': 'Static preserved firmware, not validated live widget state',
              'sha256': hashlib.sha256(raw).hexdigest(), 'constructor': '0x56c92c',
              'got_slot': hex(got_slot), 'vtable': hex(vtable),
              'slots': sorted(slots, key=lambda row: int(row['offset'],16))}
    names = {row['offset']: row['symbol'] for row in slots}
    assert names['0x68'] == '_ZN2ux6wgtsys10WidgetBase12onMouseEventERKNS0_10MouseEventE'
    assert names['0x6c'] == '_ZN2ux6wgtsys10WidgetBase16onMouseEventHookERKNS0_10MouseEventE'
    assert names['0x108'] == '_ZN20LayoutableWidgetBase16setDefWidgetModeEN2ux6wgtsys6Widget10WidgetModeE'
    destination = ROOT / 'artifacts/analysis/menu-widget-audit-20261105.json'
    destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(destination)
    for offset in ('0x68', '0x6c', '0x108'):
        print(offset, names[offset])


if __name__ == '__main__':
    main()
